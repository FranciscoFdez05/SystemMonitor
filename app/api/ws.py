"""Endpoint WebSocket.

Cada conexion tiene dos tareas: una lee los mensajes de control del cliente
(que canales quiere) y otra drena su cola hacia el socket. Separarlas evita
que un cliente lento bloquee al productor de metricas.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..core.hardening import origin_is_same_site
from ..core.hub import Client, hub
from ..core.scheduler import scheduler
from ..core.security import user_from_websocket
from ..metrics.registry import FAST_CHANNELS, SLOW_CHANNELS

log = logging.getLogger(__name__)
router = APIRouter()

VALID_CHANNELS = set(FAST_CHANNELS) | set(SLOW_CHANNELS)
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403


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


def _discard(task: asyncio.Task) -> None:
    """Marca el resultado como consumido.

    Sin esto, asyncio avisa por consola de "excepcion nunca recuperada" cuando
    la tarea termina con el error de socket cerrado, que aqui es lo normal.
    """
    if not task.cancelled():
        task.exception()


async def _writer(client: Client) -> None:
    """Envia lo que el hub va dejando en la cola del cliente."""
    while True:
        message = await client.queue.get()
        await client.ws.send_json(message)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(default=None)):
    if not origin_is_same_site(websocket.headers):
        # Cierre sin aceptar: no hay nada que negociar con un origen ajeno.
        log.warning("handshake WebSocket rechazado desde origen %r",
                    websocket.headers.get("origin"))
        await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
        return

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
        # El cierre no espera a nada a proposito. Cancelar y esperar a las
        # tareas exige otra vuelta del bucle de eventos, y para entonces el
        # cliente ya puede haber cerrado la conexion entera: el endpoint se
        # quedaba a medio desmontar y quien lo invoca lo cancelaba, que es de
        # donde salia un CancelledError intermitente al cerrar la pestana.
        # Cancelar basta: el bucle las recoge por su cuenta.
        hub.unregister(client)
        for task in (reader, writer):
            task.cancel()
            task.add_done_callback(_discard)
        # El socket tampoco se cierra a mano: el servidor ASGI lo cierra al
        # retornar el endpoint.
