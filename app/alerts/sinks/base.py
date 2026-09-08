from __future__ import annotations

from typing import Any


class Sink:
    name = "base"

    def available(self) -> bool:
        return True

    async def send(self, event: dict[str, Any]) -> str:
        raise NotImplementedError


def format_message(event: dict[str, Any], emoji: bool = True) -> str:
    """Texto de la notificacion.

    Los emojis ayudan en Telegram y Discord, pero en un log escrito a fichero
    (o a una consola que no sea UTF-8) acaban como "\\U0001f534" y ensucian la
    linea, asi que el sink de log los desactiva.
    """
    firing = event["state"] == "firing"
    verb = "DISPARADA" if firing else "RESUELTA"
    icon = (("🔴" if firing else "🟢") + " ") if emoji else ""
    symbol = ">" if event["operator"] == "gt" else "<"
    target = f" ({event['target']})" if event.get("target") else ""
    return (f"{icon}[{event['host']}] Alerta {verb}: {event['rule_name']}\n"
            f"{event['metric']}{target} = {event['value']} "
            f"(umbral {symbol} {event['threshold']})")
