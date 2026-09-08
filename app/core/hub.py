"""Hub de WebSockets con suscripcion por canal.

Que cada cliente declare que canales mira es lo que permite no ejecutar los
colectores caros cuando nadie los esta viendo. Un cliente en la pestana de CPU
no hace que la Pi recorra /proc entero cada 6 segundos.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)

_ids = itertools.count(1)


class Client:
    def __init__(self, websocket: WebSocket, username: str) -> None:
        self.id = next(_ids)
        self.ws = websocket
        self.username = username
        self.channels: set[str] = set()
        # Cola acotada: si un cliente lento no drena, se descartan sus mensajes
        # antiguos en vez de acumular memoria o frenar al resto.
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)

    def offer(self, message: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(message)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass


class Hub:
    def __init__(self) -> None:
        self._clients: set[Client] = set()
        self._on_change: list[Any] = []

    def register(self, client: Client) -> None:
        self._clients.add(client)
        log.info("cliente %s conectado (%s), total=%d",
                 client.id, client.username, len(self._clients))
        self._notify_change()

    def unregister(self, client: Client) -> None:
        self._clients.discard(client)
        log.info("cliente %s desconectado, total=%d", client.id, len(self._clients))
        self._notify_change()

    def set_channels(self, client: Client, channels: set[str]) -> None:
        client.channels = channels
        self._notify_change()

    def on_change(self, callback: Any) -> None:
        """Permite al scheduler reaccionar al instante cuando alguien se suscribe."""
        self._on_change.append(callback)

    def _notify_change(self) -> None:
        for callback in self._on_change:
            try:
                callback(self.active_channels())
            except Exception:
                log.exception("callback de cambio de suscripciones fallo")

    def active_channels(self) -> set[str]:
        return set().union(*(c.channels for c in self._clients)) if self._clients else set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        if not self._clients:
            return
        message = {"type": "metrics", "channel": channel, "data": payload}
        for client in self._clients:
            if channel in client.channels:
                client.offer(message)

    def broadcast_event(self, event: str, payload: dict[str, Any]) -> None:
        """Eventos fuera de banda (alertas, kills) que van a todos los clientes."""
        message = {"type": event, "data": payload}
        for client in self._clients:
            client.offer(message)


hub = Hub()
