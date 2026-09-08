"""Uso de CPU, frecuencia y carga."""
from __future__ import annotations

import os
from typing import Any

import psutil

from .base import Collector


class CpuCollector(Collector):
    name = "cpu"

    def __init__(self) -> None:
        self.logical = psutil.cpu_count(logical=True) or 1
        self.physical = psutil.cpu_count(logical=False) or self.logical
        # La primera llamada a cpu_percent siempre devuelve 0.0 porque no hay
        # lectura previa contra la que comparar: la consumimos al arrancar.
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)

    def collect(self) -> dict[str, Any]:
        percent = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)

        freq_current = freq_min = freq_max = None
        try:
            freq = psutil.cpu_freq()
            if freq:
                freq_current, freq_min, freq_max = freq.current, freq.min, freq.max
        except (OSError, AttributeError, NotImplementedError):
            pass

        # getloadavg no existe en Windows; el objetivo es Linux pero esto
        # permite probar los colectores en la maquina de desarrollo.
        try:
            load1, load5, load15 = os.getloadavg()
        except (OSError, AttributeError):
            load1 = load5 = load15 = 0.0

        return {
            "percent": round(percent, 1),
            "per_core": [round(c, 1) for c in per_core],
            "cores_logical": self.logical,
            "cores_physical": self.physical,
            "freq_mhz": round(freq_current, 0) if freq_current else None,
            "freq_min_mhz": round(freq_min, 0) if freq_min else None,
            "freq_max_mhz": round(freq_max, 0) if freq_max else None,
            "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
            # Carga normalizada: >100% significa mas trabajo pendiente que nucleos.
            "load_percent": round(load1 / self.logical * 100, 1),
        }
