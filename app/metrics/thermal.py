"""Temperatura y throttling.

Orden de preferencia:
  1. /sys/class/thermal  -> funciona dentro del contenedor montando /sys.
  2. psutil.sensors_temperatures() -> portable, cubre otros SBC y x86.
  3. vcgencmd -> solo si se ejecuta nativo en Raspberry Pi OS.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil

from ..config import settings
from .base import Collector

log = logging.getLogger(__name__)

# Bits devueltos por get_throttled en el firmware de la Raspberry Pi.
THROTTLE_BITS = {
    0: ("undervoltage", "Bajo voltaje ahora mismo"),
    1: ("freq_capped", "Frecuencia ARM limitada ahora mismo"),
    2: ("throttled", "Throttling activo ahora mismo"),
    3: ("soft_temp_limit", "Limite blando de temperatura activo"),
    16: ("undervoltage_past", "Ha habido bajo voltaje desde el arranque"),
    17: ("freq_capped_past", "Ha habido limitacion de frecuencia"),
    18: ("throttled_past", "Ha habido throttling desde el arranque"),
    19: ("soft_temp_limit_past", "Se alcanzo el limite blando de temperatura"),
}

TEMP_WARN = 70.0
TEMP_CRIT = 80.0


class ThermalCollector(Collector):
    name = "thermal"

    def __init__(self) -> None:
        self._zone: Path | None = self._find_thermal_zone()
        self._throttle_file: Path | None = self._find_throttle_file()
        self._vcgencmd: str | None = shutil.which("vcgencmd")
        if not self._zone and not self._vcgencmd:
            log.info("sin zona termica en %s; se usara psutil.sensors_temperatures",
                     settings.sys_path)

    def _find_thermal_zone(self) -> Path | None:
        base = Path(settings.sys_path) / "class" / "thermal"
        if not base.is_dir():
            return None
        zones = sorted(base.glob("thermal_zone*"))
        # Preferimos explicitamente la zona de la CPU; en la Pi es cpu-thermal.
        for zone in zones:
            try:
                kind = (zone / "type").read_text().strip().lower()
            except OSError:
                continue
            if any(tag in kind for tag in ("cpu", "soc", "package")):
                return zone
        return zones[0] if zones else None

    def _find_throttle_file(self) -> Path | None:
        candidate = Path(settings.sys_path) / "devices/platform/soc/soc:firmware/get_throttled"
        return candidate if candidate.exists() else None

    def _read_temp(self) -> float | None:
        if self._zone:
            try:
                raw = (self._zone / "temp").read_text().strip()
                # El kernel expone milicelsius.
                return int(raw) / 1000.0
            except (OSError, ValueError):
                pass
        try:
            sensors = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            sensors = {}
        for key in ("cpu_thermal", "coretemp", "cpu-thermal", "k10temp", "soc_thermal"):
            if sensors.get(key):
                return sensors[key][0].current
        for readings in sensors.values():
            if readings:
                return readings[0].current
        if self._vcgencmd:
            try:
                out = subprocess.run([self._vcgencmd, "measure_temp"], capture_output=True,
                                     text=True, timeout=2).stdout
                return float(out.split("=")[1].split("'")[0])
            except (OSError, IndexError, ValueError, subprocess.SubprocessError):
                pass
        return None

    def _read_throttled(self) -> dict[str, Any] | None:
        raw: str | None = None
        if self._throttle_file:
            try:
                raw = self._throttle_file.read_text().strip()
            except OSError:
                raw = None
        if raw is None and self._vcgencmd:
            try:
                out = subprocess.run([self._vcgencmd, "get_throttled"], capture_output=True,
                                     text=True, timeout=2).stdout
                raw = out.strip().split("=")[-1]
            except (OSError, IndexError, subprocess.SubprocessError):
                raw = None
        if not raw:
            return None
        try:
            value = int(raw, 16) if raw.startswith("0x") else int(raw)
        except ValueError:
            return None
        flags = {name: bool(value & (1 << bit)) for bit, (name, _) in THROTTLE_BITS.items()}
        active = [desc for bit, (name, desc) in THROTTLE_BITS.items() if value & (1 << bit)]
        return {"raw": hex(value), "flags": flags, "messages": active}

    def collect(self) -> dict[str, Any]:
        temp = self._read_temp()
        if temp is None:
            level = "unknown"
        elif temp >= TEMP_CRIT:
            level = "critical"
        elif temp >= TEMP_WARN:
            level = "warning"
        else:
            level = "ok"
        return {
            "temp_c": round(temp, 1) if temp is not None else None,
            "level": level,
            "warn_at": TEMP_WARN,
            "crit_at": TEMP_CRIT,
            "throttling": self._read_throttled(),
        }
