"""RAM y swap."""
from __future__ import annotations

from typing import Any

import psutil

from .base import Collector


class MemoryCollector(Collector):
    name = "memory"

    def collect(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return {
            "total": vm.total,
            "used": vm.total - vm.available,
            "available": vm.available,
            "free": vm.free,
            "percent": round(vm.percent, 1),
            # cached/buffers no existen fuera de Linux; getattr evita el AttributeError.
            "cached": getattr(vm, "cached", 0),
            "buffers": getattr(vm, "buffers", 0),
            "swap_total": sw.total,
            "swap_used": sw.used,
            "swap_percent": round(sw.percent, 1),
        }
