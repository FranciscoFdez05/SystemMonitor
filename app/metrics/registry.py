"""Punto unico de acceso a los colectores.

Agrupa por cadencia: los del tick rapido son lecturas de contadores (coste en
microsegundos) y los del lento recorren /proc entero, asi que solo se ejecutan
cuando alguien los esta mirando.
"""
from __future__ import annotations

import logging
from typing import Any

import psutil

from ..config import settings
from .cpu import CpuCollector
from .disk import DiskCollector
from .memory import MemoryCollector
from .network import BandwidthCollector, ConnectionsCollector
from .processes import ProcessCollector
from .system import SystemCollector
from .thermal import ThermalCollector

log = logging.getLogger(__name__)

FAST_CHANNELS = ("cpu", "memory", "thermal", "network", "system")
SLOW_CHANNELS = ("disk", "processes", "connections")


class MetricsRegistry:
    def __init__(self) -> None:
        if settings.procfs_path:
            # Solo necesario si el contenedor NO comparte el PID namespace del host.
            psutil.PROCFS_PATH = settings.procfs_path
            log.info("psutil leyendo de %s", settings.procfs_path)

        self.cpu = CpuCollector()
        self.memory = MemoryCollector()
        self.thermal = ThermalCollector()
        self.network = BandwidthCollector()
        self.system = SystemCollector()
        self.disk = DiskCollector()
        self.processes = ProcessCollector()
        self.connections = ConnectionsCollector()

        self._fast = {
            "cpu": self.cpu, "memory": self.memory, "thermal": self.thermal,
            "network": self.network, "system": self.system,
        }
        self._slow = {
            "disk": self.disk, "processes": self.processes, "connections": self.connections,
        }
        self.all = {**self._fast, **self._slow}

    async def fast_snapshot(self) -> dict[str, Any]:
        return {name: await c.acollect() for name, c in self._fast.items()}

    async def slow_snapshot(self, channels: set[str] | None = None) -> dict[str, Any]:
        wanted = self._slow.keys() if channels is None else (channels & self._slow.keys())
        return {name: await self._slow[name].acollect() for name in wanted}

    async def full_snapshot(self) -> dict[str, Any]:
        return {**await self.fast_snapshot(), **await self.slow_snapshot()}


registry = MetricsRegistry()
