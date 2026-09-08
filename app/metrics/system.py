"""Identidad del host y uptimes."""
from __future__ import annotations

import os
import platform
import socket
import time
from pathlib import Path
from typing import Any

import psutil

from ..config import settings
from .base import Collector

APP_START = time.time()


def _hardware_model() -> str:
    """Lee el modelo del device tree; en la Pi da 'Raspberry Pi 4 Model B Rev 1.4'."""
    for candidate in (
        Path(settings.sys_path) / "firmware/devicetree/base/model",
        Path("/proc/device-tree/model"),
    ):
        try:
            # El device tree termina las cadenas con NUL.
            return candidate.read_bytes().decode("utf-8", "ignore").strip("\x00").strip()
        except OSError:
            continue
    return platform.machine()


class SystemCollector(Collector):
    name = "system"

    def __init__(self) -> None:
        self.static = {
            "hostname": socket.gethostname(),
            "model": _hardware_model(),
            "kernel": platform.release(),
            "arch": platform.machine(),
            "python": platform.python_version(),
            "boot_time": psutil.boot_time(),
            "app_start": APP_START,
            "in_container": Path("/.dockerenv").exists(),
            "pid": os.getpid(),
        }

    def collect(self) -> dict[str, Any]:
        now = time.time()
        proc = psutil.Process()
        with proc.oneshot():
            app_rss = proc.memory_info().rss
            app_cpu = proc.cpu_percent(interval=None)
        return {
            **self.static,
            "uptime_seconds": int(now - self.static["boot_time"]),
            "app_uptime_seconds": int(now - APP_START),
            # El coste del propio monitor, visible en el dashboard: si esto sube,
            # se nota antes de que se convierta en un problema.
            "app_rss": app_rss,
            "app_cpu_percent": round(app_cpu, 1),
            "timestamp": now,
        }
