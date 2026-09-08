"""Verificacion de la capa de metricas sin levantar el servidor.

    python -m app.metrics.dump            # todo, una vez
    python -m app.metrics.dump cpu memory # solo esos canales
    python -m app.metrics.dump --watch    # refresco continuo

Sirve para contrastar los numeros contra htop / free -h / df -h antes de
meter web, WebSockets y base de datos por medio.
"""
from __future__ import annotations

import asyncio
import json
import sys

from .registry import registry


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    watch = "--watch" in sys.argv or "-w" in sys.argv
    channels = set(args) if args else None

    if channels:
        unknown = channels - registry.all.keys()
        if unknown:
            print(f"canales desconocidos: {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"disponibles: {', '.join(sorted(registry.all))}", file=sys.stderr)
            return 2

    while True:
        selected = channels or set(registry.all)
        data = {name: await registry.all[name].acollect() for name in sorted(selected)}
        if watch:
            print("\033[2J\033[H", end="")
        print(json.dumps(data, indent=2, default=str))
        if not watch:
            return 0
        await asyncio.sleep(2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
