from __future__ import annotations

import logging
from typing import Any

from .base import Sink, format_message

log = logging.getLogger("alerts")


class LogSink(Sink):
    """Siempre disponible: es la red de seguridad si no hay webhook configurado."""

    name = "log"

    async def send(self, event: dict[str, Any]) -> str:
        message = format_message(event, emoji=False).replace("\n", " | ")
        if event["state"] == "firing":
            log.warning(message)
        else:
            log.info(message)
        return "ok"
