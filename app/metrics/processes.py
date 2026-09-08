"""Listado de procesos y terminacion controlada."""
from __future__ import annotations

import logging
import os
import signal
import time
from typing import Any

import psutil

from ..config import settings
from .base import Collector

log = logging.getLogger(__name__)

ATTRS = ["pid", "name", "username", "cpu_percent", "memory_percent", "memory_info",
         "status", "create_time", "num_threads"]


class KillError(Exception):
    """Peticion de kill rechazada por politica o imposible de cumplir."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class ProcessCollector(Collector):
    name = "processes"
    heavy = True

    def __init__(self, limit: int = 120) -> None:
        self.limit = limit
        self._cores = psutil.cpu_count(logical=True) or 1
        self._primed = False

    def _iter(self) -> list[dict[str, Any]]:
        rows = []
        for proc in psutil.process_iter(ATTRS, ad_value=None):
            info = proc.info
            if info["pid"] == 0:
                continue
            cpu = info["cpu_percent"] or 0.0
            mem_info = info["memory_info"]
            rows.append({
                "pid": info["pid"],
                "name": info["name"] or "?",
                "user": info["username"] or "?",
                # psutil suma el uso de todos los nucleos: un proceso a tope en
                # 4 hilos da 400%. Normalizamos para que sea comparable con la
                # grafica global de CPU.
                "cpu": round(cpu / self._cores, 1),
                "cpu_raw": round(cpu, 1),
                "mem": round(info["memory_percent"] or 0.0, 1),
                "rss": mem_info.rss if mem_info else 0,
                "status": info["status"] or "?",
                "threads": info["num_threads"] or 0,
                "started": info["create_time"],
            })
        return rows

    def collect(self) -> dict[str, Any]:
        rows = self._iter()
        if not self._primed:
            # process_iter cachea los objetos Process, pero la primera lectura de
            # cpu_percent de cada uno vale 0.0. Se descarta y se repite tras una
            # pausa corta para que el primer render no salga todo a cero.
            self._primed = True
            time.sleep(0.25)
            rows = self._iter()

        rows.sort(key=lambda r: (-r["cpu"], -r["mem"]))
        by_status: dict[str, int] = {}
        for row in rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1

        return {
            "processes": rows[: self.limit],
            "total": len(rows),
            "shown": min(len(rows), self.limit),
            "by_status": by_status,
            "can_kill": settings.allow_kill,
        }


def kill_process(pid: int, force: bool = False) -> dict[str, Any]:
    """Envia SIGTERM (o SIGKILL con force) aplicando las reglas de seguridad."""
    if not settings.allow_kill:
        raise KillError("La terminacion de procesos esta desactivada (SM_ALLOW_KILL)", 403)
    if pid <= 1:
        raise KillError("PID protegido: no se puede terminar init/kernel", 403)
    if pid == os.getpid():
        raise KillError("El monitor no puede terminarse a si mismo", 403)

    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = proc.name()
            try:
                username = proc.username()
            except (psutil.AccessDenied, KeyError):
                username = "?"
            try:
                proc_uid = proc.uids().real
            except (psutil.AccessDenied, AttributeError):
                proc_uid = None
    except psutil.NoSuchProcess:
        raise KillError(f"El proceso {pid} ya no existe", 404) from None
    except psutil.AccessDenied:
        raise KillError(f"Sin permisos para inspeccionar el proceso {pid}", 403) from None

    if name.lower() in settings.protected_list:
        raise KillError(f"'{name}' esta en la lista de procesos protegidos", 403)

    own_uid = os.getuid() if hasattr(os, "getuid") else None
    if (not settings.allow_kill_foreign and own_uid is not None
            and own_uid != 0 and proc_uid is not None and proc_uid != own_uid):
        raise KillError(
            f"'{name}' pertenece a otro usuario ({username}). "
            "Activa SM_ALLOW_KILL_FOREIGN si de verdad lo necesitas.", 403)

    try:
        proc.send_signal(signal.SIGKILL if force else signal.SIGTERM)
    except psutil.NoSuchProcess:
        raise KillError(f"El proceso {pid} ya no existe", 404) from None
    except psutil.AccessDenied:
        raise KillError(f"Permiso denegado al señalar el proceso {pid}", 403) from None

    # Damos margen a un cierre limpio antes de responder para que la UI pueda
    # decir si el proceso murio de verdad o sigue vivo.
    gone = True
    try:
        proc.wait(timeout=1.5)
    except psutil.TimeoutExpired:
        gone = False
    except psutil.NoSuchProcess:
        pass

    log.warning("kill pid=%s name=%s user=%s force=%s terminado=%s",
                pid, name, username, force, gone)
    return {"pid": pid, "name": name, "user": username, "signal":
            "SIGKILL" if force else "SIGTERM", "terminated": gone}
