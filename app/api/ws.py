"""Endpoint WebSocket.

Cada conexion tiene dos tareas: una lee los mensajes de control del cliente
(que canales quiere) y otra drena su cola hacia el socket. Separarlas evita
que un cliente lento bloquee al productor de metricas.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..core.hub import Client, hub
from ..core.scheduler import scheduler
from ..core.security import user_from_websocket
from ..metrics.registry import FAST_CHANNELS, SLOW_CHANNELS

log = logging.getLogger(__name__)
router = APIRouter()

VALID_CHANNELS = set(FAST_CHANNELS) | set(SLOW_CHANNELS)
CLOSE_UNAUTHORIZED = 4401


async def _reader(client: Client) -> None:
    """Procesa los mensajes de control entrantes.

    No escribe nunca en el socket directamente: encola. Dos corrutinas
    enviando a la vez sobre el mismo WebSocket es una carrera que acaba en
    CancelledError o en tramas entrelazadas, asi que todas las salidas pasan
    por `_writer`.
    """
    while True:
        message = await client.ws.receive_json()
        action = message.get("action")
        if action == "subscribe":
            requested = set(message.get("channels") or [])
            unknown = requested - VALID_CHANNELS
            channels = requested & VALID_CHANNELS
            hub.set_channels(client, channels)
            client.offer({
                "type": "subscribed",
                "data": {"channels": sorted(channels), "ignored": sorted(unknown)},
            })
            # Respuesta inmediata con lo ultimo conocido: sin esto la interfaz
            # se queda en blanco hasta el siguiente tick.
            snapshot = scheduler.snapshot()
            for channel in channels:
                if channel in snapshot:
                    client.offer({
                        "type": "metrics", "channel": channel, "data": snapshot[channel],
                    })
        elif action == "ping":
            client.offer({"type": "pong", "data": {}})


async def _writer(client: Client) -> None:
    """Envia lo que el hub va dejando en la cola del cliente."""
    while True:
        message = await client.queue.get()
        await client.ws.send_json(message)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(default=None)):
    username = user_from_websocket(dict(websocket.cookies), token)
    if not username:
        # Se acepta para poder cerrar con un codigo propio: si se rechaza el
        # handshake sin mas, el navegador solo ve un error generico y el cliente
        # no puede distinguir "sesion caducada" de "servidor caido".
        await websocket.accept()
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Sesion no valida")
        return

    await websocket.accept()
    client = Client(websocket, username)
    # El saludo se encola antes de arrancar el escritor, que lo enviara como
    # primer mensaje: asi tampoco este compite por el socket.
    client.offer({
        "type": "hello",
        "data": {"username": username, "channels": sorted(VALID_CHANNELS),
                 "fast_channels": sorted(FAST_CHANNELS)},
    })
    hub.register(client)

    reader = asyncio.create_task(_reader(client))
    writer = asyncio.create_task(_writer(client))
    try:
        done, pending = await asyncio.wait({reader, writer},
                                           return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            # .exception() sobre una tarea cancelada relanza CancelledError, y
            # esa no hereda de Exception: se escaparia de este handler y
            # cancelaria la propia conexion. Se comprueba antes de preguntar.
            if task.cancelled():
                continue
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("error en la conexion WebSocket del cliente %s", client.id)
    finally:
        reader.cancel()
        writer.cancel()
        await asyncio.gather(reader, writer, return_exceptions=True)
        hub.unregister(client)
        if websocket.client_state is not WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except RuntimeError:
                pass
