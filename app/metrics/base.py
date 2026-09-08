"""Contrato comun de los colectores.

Un colector es un objeto con estado (necesita recordar la lectura anterior para
calcular tasas) y un metodo `collect()` sincrono. El scheduler decide cuando
llamarlo; los marcados como `heavy` se ejecutan en un hilo aparte para no
bloquear el event loop mientras iteran /proc.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class Collector:
    name: str = "base"
    heavy: bool = False

    def collect(self) -> dict[str, Any]:
        raise NotImplementedError

    async def acollect(self) -> dict[str, Any]:
        try:
            if self.heavy:
                return await asyncio.to_thread(self.collect)
            return self.collect()
        except Exception:
            log.exception("colector %s fallo", self.name)
            return {"error": True}


class RateTracker:
    """Convierte contadores monotonos acumulados en tasas por segundo."""

    def __init__(self) -> None:
        self._prev: dict[str, float] = {}
        self._prev_ts: float | None = None

    def update(self, counters: dict[str, float]) -> dict[str, float]:
        now = time.monotonic()
        rates: dict[str, float] = {}
        if self._prev_ts is not None:
            elapsed = now - self._prev_ts
            if elapsed > 0:
                for key, value in counters.items():
                    previous = self._prev.get(key)
                    # Un contador que retrocede significa reinicio de interfaz o
                    # desbordamiento: se descarta la muestra en vez de emitir un pico.
                    if previous is not None and value >= previous:
                        rates[key] = (value - previous) / elapsed
        self._prev = dict(counters)
        self._prev_ts = now
        return rates
