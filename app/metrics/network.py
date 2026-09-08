"""Trafico de red, conexiones activas y atribucion por proceso.

Aviso importante sobre "top procesos por red": Linux no expone bytes de red por
proceso. /proc/<pid>/net/dev pertenece al namespace de red, no al proceso, asi
que todos los procesos del mismo namespace ven los mismos contadores. Medir
bytes reales por proceso exige nethogs o eBPF. Lo que si es barato y responde a
la pregunta util ("quien esta hablando con el exterior") es agrupar las
conexiones abiertas por proceso, que es lo que hace TopTalkers.
"""
from __future__ import annotations

import logging
import socket
from typing import Any

import psutil

from .base import Collector, RateTracker

log = logging.getLogger(__name__)

PROTO_NAMES = {
    (socket.AF_INET, socket.SOCK_STREAM): "tcp",
    (socket.AF_INET6, socket.SOCK_STREAM): "tcp6",
    (socket.AF_INET, socket.SOCK_DGRAM): "udp",
    (socket.AF_INET6, socket.SOCK_DGRAM): "udp6",
}


class BandwidthCollector(Collector):
    """Tick rapido: solo lee contadores agregados, coste despreciable."""

    name = "network"

    def __init__(self) -> None:
        self._total = RateTracker()
        self._per_nic = RateTracker()

    def collect(self) -> dict[str, Any]:
        total = psutil.net_io_counters()
        rates = self._total.update({"rx": total.bytes_recv, "tx": total.bytes_sent})

        per_nic_counters: dict[str, float] = {}
        nics: dict[str, dict[str, Any]] = {}
        try:
            for nic, counters in psutil.net_io_counters(pernic=True).items():
                if nic == "lo":
                    continue
                per_nic_counters[f"{nic}:rx"] = counters.bytes_recv
                per_nic_counters[f"{nic}:tx"] = counters.bytes_sent
                nics[nic] = {"rx_total": counters.bytes_recv, "tx_total": counters.bytes_sent}
        except (OSError, RuntimeError):
            pass
        nic_rates = self._per_nic.update(per_nic_counters)
        for nic, info in nics.items():
            info["rx_bps"] = round(nic_rates.get(f"{nic}:rx", 0.0), 1)
            info["tx_bps"] = round(nic_rates.get(f"{nic}:tx", 0.0), 1)

        return {
            "rx_bps": round(rates.get("rx", 0.0), 1),
            "tx_bps": round(rates.get("tx", 0.0), 1),
            "rx_total": total.bytes_recv,
            "tx_total": total.bytes_sent,
            "packets_recv": total.packets_recv,
            "packets_sent": total.packets_sent,
            "errors": total.errin + total.errout,
            "drops": total.dropin + total.dropout,
            "nics": nics,
        }


class ConnectionsCollector(Collector):
    """Tick lento y bajo demanda: enumerar sockets recorre /proc/<pid>/fd."""

    name = "connections"
    heavy = True

    def __init__(self) -> None:
        self._names: dict[int, str] = {}
        self.degraded = False

    def _name_for(self, pid: int | None) -> str:
        if not pid:
            return ""
        cached = self._names.get(pid)
        if cached is not None:
            return cached
        try:
            name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            name = ""
        # El PID se reutiliza, pero el mapa se limpia entero mas abajo; el riesgo
        # de nombre obsoleto dura como mucho un tick.
        self._names[pid] = name
        return name

    def collect(self) -> dict[str, Any]:
        self._names.clear()
        try:
            raw = psutil.net_connections(kind="inet")
            self.degraded = False
        except psutil.AccessDenied:
            # Sin privilegios solo se ven los sockets propios. Se avisa en la UI
            # en vez de mostrar una lista vacia sin explicacion.
            self.degraded = True
            raw = []
        except (OSError, RuntimeError):
            self.degraded = True
            raw = []

        connections = []
        by_process: dict[str, dict[str, Any]] = {}
        states: dict[str, int] = {}

        for conn in raw:
            proto = PROTO_NAMES.get((conn.family, conn.type), "other")
            laddr = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else ""
            raddr = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else ""
            name = self._name_for(conn.pid)
            status = conn.status or "NONE"
            states[status] = states.get(status, 0) + 1
            connections.append({
                "proto": proto,
                "laddr": laddr,
                "raddr": raddr,
                "status": status,
                "pid": conn.pid,
                "name": name,
            })
            if conn.pid:
                key = f"{conn.pid}"
                entry = by_process.setdefault(
                    key, {"pid": conn.pid, "name": name, "count": 0, "established": 0,
                          "listening": 0, "peers": set()})
                entry["count"] += 1
                if status == "ESTABLISHED":
                    entry["established"] += 1
                    if conn.raddr:
                        entry["peers"].add(conn.raddr.ip)
                elif status == "LISTEN":
                    entry["listening"] += 1

        # Las conexiones establecidas primero: son las que estan moviendo datos.
        connections.sort(key=lambda c: (c["status"] != "ESTABLISHED", c["name"], c["laddr"]))

        talkers = []
        for entry in by_process.values():
            entry["peers"] = sorted(entry["peers"])[:5]
            talkers.append(entry)
        talkers.sort(key=lambda t: (-t["established"], -t["count"]))

        return {
            "connections": connections[:500],
            "total": len(connections),
            "truncated": len(connections) > 500,
            "states": states,
            "top_talkers": talkers[:10],
            "degraded": self.degraded,
        }
