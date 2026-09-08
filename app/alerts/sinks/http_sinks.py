"""Sinks que salen por HTTP: webhook generico, Telegram y Discord."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ...config import settings
from .base import Sink, format_message

log = logging.getLogger(__name__)

# Timeout corto y sin reintentos: una alerta que llega tarde no sirve, y
# bloquear el bucle de metricas esperando a Telegram seria peor que perderla.
TIMEOUT = httpx.Timeout(6.0)


class WebhookSink(Sink):
    name = "webhook"

    def available(self) -> bool:
        return bool(settings.alert_webhook_url)

    async def send(self, event: dict[str, Any]) -> str:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(settings.alert_webhook_url, json=event)
        response.raise_for_status()
        return f"http {response.status_code}"


class TelegramSink(Sink):
    name = "telegram"

    def available(self) -> bool:
        return bool(settings.telegram_bot_token and settings.telegram_chat_id)

    async def send(self, event: dict[str, Any]) -> str:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": settings.telegram_chat_id, "text": format_message(event)}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        return f"http {response.status_code}"


class DiscordSink(Sink):
    name = "discord"

    def available(self) -> bool:
        return bool(settings.discord_webhook_url)

    async def send(self, event: dict[str, Any]) -> str:
        payload = {"content": format_message(event)}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(settings.discord_webhook_url, json=payload)
        response.raise_for_status()
        return f"http {response.status_code}"
