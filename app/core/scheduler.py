"""Los bucles de muestreo: un solo productor para todos los clientes.

Aqui esta la decision que mantiene el consumo bajo. En vez de que cada cliente
WebSocket pida metricas por su cuenta, hay un unico bucle que muestrea y hace
broadcast. Diez pestanas abiertas cuestan lo mismo que una.

Ademas los colectores caros (procesos, conexiones) solo se ejecutan si algun
cliente esta suscrito a ese canal.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..alerts.engine import engine
from ..config import settings
from ..metrics.registry import registry
from ..storage import retention
from ..storage.history import aggregator
from .hub import hub

log = logging.getLogger(__name__)

# El disco se muestrea siempre, aunque nadie mire la pestana: es barato (un
# statvfs por particion) y las alertas de espacio deben funcionar sin publico.
ALWAYS_ON_SLOW = {"disk"}

RETENTION_INTERVAL = 3600.0


class Scheduler:
    def __init__(self) -> None:
        self.last_fast: dict[str, Any] = {}
        self.last_slow: dict[str, Any] = {}
        self.last_fast_ts: float = 0.0
        self.last_slow_ts: float = 0.0
        self.ticks = 0
        self._tasks: list[asyncio.Task] = []
        self._wake_slow = asyncio.Event()
        self._running = False

    # ------------------------------------------------------------ ciclo vida
    async def start(self) -> None:
        self._running = True
        engine.set_broadcaster(hub.broadcast_event)
        hub.on_change(self._on_subscriptions_changed)
        self._tasks = [
            asyncio.create_task(self._fast_loop(), name="sm-fast"),
            asyncio.create_task(self._slow_loop(), name="sm-slow"),
            asyncio.create_task(self._persist_loop(), name="sm-persist"),
            asyncio.create_task(self._retention_loop(), name="sm-retention"),
        ]
        log.info("scheduler arrancado (rapido=%.1fs lento=%.1fs persistencia=%.0fs)",
                 settings.fast_interval, settings.slow_interval, settings.persist_interval)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        # Se vuelca lo acumulado para no perder el ultimo minuto al reiniciar.
        await aggregator.flush()
        log.info("scheduler detenido")

    def _on_subscriptions_changed(self, channels: set[str]) -> None:
        """Al suscribirse alguien a un canal lento, se le sirve sin esperar al tick."""
        if channels & registry.slow_channels:
            self._wake_slow.set()

    # ---------------------------------------------------------------- bucles
    async def _fast_loop(self) -> None:
        while self._running:
            started = time.monotonic()
            try:
                snapshot = await registry.fast_snapshot()
                self.last_fast = snapshot
                self.last_fast_ts = time.time()
                self.ticks += 1

                for channel, payload in snapshot.items():
                    hub.broadcast(channel, payload)

                aggregator.add(snapshot)
                # Las alertas se evaluan sobre metricas rapidas + el ultimo disco
                # conocido, para que las reglas de espacio tengan datos.
                await engine.evaluate({**snapshot, **self.last_slow})
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fallo en el tick rapido")
            await self._sleep_remaining(started, settings.fast_interval)

    async def _slow_loop(self) -> None:
        while self._running:
            started = time.monotonic()
            try:
                wanted = (hub.active_channels() & registry.slow_channels) | ALWAYS_ON_SLOW
                snapshot = await registry.slow_snapshot(wanted)
                # Merge en vez de reemplazo: si nadie mira procesos, se conserva
                # la ultima lista conocida en vez de dejar el canal vacio.
                self.last_slow.update(snapshot)
                self.last_slow_ts = time.time()

                for channel, payload in snapshot.items():
                    hub.broadcast(channel, payload)

                if "disk" in snapshot:
                    aggregator.set_disk(registry.disk.root_percent(snapshot["disk"]))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fallo en el tick lento")

            # Espera interrumpible: si alguien abre la pestana de procesos, el
            # Event corta la espera y los datos llegan al momento.
            elapsed = time.monotonic() - started
            try:
                await asyncio.wait_for(self._wake_slow.wait(),
                                       max(0.1, settings.slow_interval - elapsed))
            except TimeoutError:
                pass
            finally:
                self._wake_slow.clear()

    async def _persist_loop(self) -> None:
        while self._running:
            await asyncio.sleep(settings.persist_interval)
            try:
                await aggregator.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fallo al persistir el historico")

    async def _retention_loop(self) -> None:
        while self._running:
            try:
                await retention.purge()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fallo en la purga del historico")
            await asyncio.sleep(RETENTION_INTERVAL)

    @staticmethod
    async def _sleep_remaining(started: float, interval: float) -> None:
        """Duerme descontando lo que costo el trabajo, para no derivar."""
        await asyncio.sleep(max(0.05, interval - (time.monotonic() - started)))

    # ----------------------------------------------------------------- salud
    def snapshot(self) -> dict[str, Any]:
        return {**self.last_fast, **self.last_slow}

    def health(self) -> dict[str, Any]:
        now = time.time()
        fast_age = now - self.last_fast_ts if self.last_fast_ts else None
        # Se considera atascado si lleva sin producir mas de tres intervalos.
        stalled = fast_age is None or fast_age > settings.fast_interval * 3
        return {
            "running": self._running,
            "ticks": self.ticks,
            "last_fast_age": round(fast_age, 2) if fast_age is not None else None,
            "last_slow_age": (round(now - self.last_slow_ts, 2)
                              if self.last_slow_ts else None),
            "stalled": stalled,
            "clients": hub.client_count,
            "active_channels": sorted(hub.active_channels()),
        }


scheduler = Scheduler()
