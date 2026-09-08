"""Particiones, ocupacion y E/S de disco.

Dentro de Docker el sistema de ficheros del host se monta en SM_HOST_ROOT
(p.ej. /host/root). statvfs opera sobre rutas reales, no sobre /proc, asi que
hay que consultar la ruta montada y traducir el nombre para mostrarlo.
"""
from __future__ import annotations

import os
from typing import Any

import psutil

from ..config import settings
from .base import Collector, RateTracker

# Pseudo-sistemas de ficheros: ocupan 0 o son vistas del kernel, no interesan.
VIRTUAL_FSTYPES = {
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs",
    "devpts", "devtmpfs", "efivarfs", "fuse.gvfsd-fuse", "fusectl", "hugetlbfs",
    "mqueue", "nsfs", "overlay", "proc", "pstore", "ramfs", "securityfs",
    "squashfs", "sysfs", "tmpfs", "tracefs",
}

LOW_SPACE_WARN = 20.0   # % libre por debajo del cual se avisa
LOW_SPACE_CRIT = 10.0   # % libre por debajo del cual es critico


def _display_path(mountpoint: str) -> str:
    """Convierte /host/root/boot en /boot para que el usuario reconozca la ruta."""
    root = settings.host_root.rstrip("/")
    if root and mountpoint.startswith(root):
        stripped = mountpoint[len(root):]
        return stripped or "/"
    return mountpoint


class DiskCollector(Collector):
    name = "disk"
    heavy = True  # statvfs puede bloquear sobre montajes de red caidos

    def __init__(self) -> None:
        self._io = RateTracker()

    def _candidate_mounts(self) -> list[tuple[str, str, str]]:
        """Devuelve (mountpoint_real, device, fstype) de las particiones reales."""
        found: dict[str, tuple[str, str, str]] = {}
        root = settings.host_root.rstrip("/")

        for part in psutil.disk_partitions(all=False):
            if part.fstype.lower() in VIRTUAL_FSTYPES:
                continue
            # Con el host montado en /host/root ignoramos las rutas del propio
            # contenedor: son la imagen Docker, no el disco que interesa.
            if root and not part.mountpoint.startswith(root):
                continue
            found[part.mountpoint] = (part.mountpoint, part.device, part.fstype)

        # Un bind mount no recursivo solo expone la raiz. Los montajes extra
        # configurados a mano cubren ese caso.
        for extra in settings.extra_mount_list:
            real = os.path.join(root, extra.lstrip("/")) if root else extra
            if os.path.isdir(real):
                found.setdefault(real, (real, "", ""))

        if not found and os.path.isdir(settings.host_root):
            found[settings.host_root] = (settings.host_root, "", "")
        return list(found.values())

    def collect(self) -> dict[str, Any]:
        partitions = []
        for mountpoint, device, fstype in self._candidate_mounts():
            try:
                usage = psutil.disk_usage(mountpoint)
            except (PermissionError, OSError):
                continue
            if usage.total == 0:
                continue
            free_pct = usage.free / usage.total * 100
            if free_pct < LOW_SPACE_CRIT:
                level = "critical"
            elif free_pct < LOW_SPACE_WARN:
                level = "warning"
            else:
                level = "ok"
            partitions.append({
                "mount": _display_path(mountpoint),
                "device": device,
                "fstype": fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": round(usage.percent, 1),
                "free_percent": round(free_pct, 1),
                "level": level,
            })

        partitions.sort(key=lambda p: (p["mount"] != "/", p["mount"]))

        io_rates: dict[str, float] = {}
        try:
            io = psutil.disk_io_counters()
            if io:
                io_rates = self._io.update({
                    "read_bytes": io.read_bytes,
                    "write_bytes": io.write_bytes,
                })
        except (OSError, RuntimeError):
            pass

        return {
            "partitions": partitions,
            "io": {
                "read_bps": round(io_rates.get("read_bytes", 0.0), 1),
                "write_bps": round(io_rates.get("write_bytes", 0.0), 1),
            },
        }

    def root_percent(self, data: dict[str, Any]) -> float | None:
        """Ocupacion de la particion principal, para la serie del historico.

        En Linux siempre existe "/" y el orden de `collect` la deja la primera.
        El respaldo cubre el desarrollo en Windows, donde los montajes son
        C:\\, D:\\... y si no hubiera respaldo la columna del historico saldria
        siempre vacia. Las reglas de alerta siguen exigiendo el punto de
        montaje exacto: ahi un respaldo silencioso vigilaria el disco
        equivocado.
        """
        partitions = data.get("partitions", [])
        for part in partitions:
            if part["mount"] == "/":
                return part["percent"]
        return partitions[0]["percent"] if partitions else None
