"""Acumulacion en memoria y escritura de agregados por minuto."""
from __future__ import annotations

import logging
import time
from typing import Any

from .db import db

log = logging.getLogger(__name__)


class HistoryAggregator:
    """Acumula las muestras del tick rapido y las condensa en una fila/minuto.

    Guardar cada muestra de 2 s serian 43.200 filas al dia y ninguna grafica
    necesita esa resolucion pasadas unas horas. Se guarda la media, y ademas el
    pico de CPU para no perder los picos cortos al promediar.
    """

    FIELDS = ("cpu_pct", "temp_c", "freq_mhz", "mem_pct", "mem_used", "mem_total",
              "swap_pct", "net_rx", "net_tx", "disk_pct", "load1")

    def __init__(self) -> None:
        self._sums: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._cpu_peak = 0.0
        self._disk_pct: float | None = None

    def add(self, snapshot: dict[str, Any]) -> None:
        cpu = snapshot.get("cpu") or {}
        mem = snapshot.get("memory") or {}
        thermal = snapshot.get("thermal") or {}
        net = snapshot.get("network") or {}

        values = {
            "cpu_pct": cpu.get("percent"),
            "temp_c": thermal.get("temp_c"),
            "freq_mhz": cpu.get("freq_mhz"),
            "mem_pct": mem.get("percent"),
            "mem_used": mem.get("used"),
            "mem_total": mem.get("total"),
            "swap_pct": mem.get("swap_percent"),
            "net_rx": net.get("rx_bps"),
            "net_tx": net.get("tx_bps"),
            "load1": (cpu.get("load") or [None])[0],
        }
        for key, value in values.items():
            if isinstance(value, (int, float)):
                self._sums[key] = self._sums.get(key, 0.0) + float(value)
                self._counts[key] = self._counts.get(key, 0) + 1

        if isinstance(values["cpu_pct"], (int, float)):
            self._cpu_peak = max(self._cpu_peak, float(values["cpu_pct"]))

    def set_disk(self, root_percent: float | None) -> None:
        # El disco viene del tick lento, no del rapido: se guarda el ultimo valor.
        if root_percent is not None:
            self._disk_pct = root_percent

    def _average(self, key: str) -> float | None:
        count = self._counts.get(key, 0)
        return round(self._sums[key] / count, 2) if count else None

    def has_data(self) -> bool:
        return bool(self._counts)

    def reset(self) -> None:
        self._sums.clear()
        self._counts.clear()
        self._cpu_peak = 0.0

    async def flush(self) -> bool:
        if not self.has_data():
            return False
        # Alineado al minuto: hace que INSERT OR REPLACE sea idempotente y que
        # los puntos de la grafica caigan en una rejilla regular.
        ts = int(time.time()) // 60 * 60
        row = {key: self._average(key) for key in self.FIELDS if key != "disk_pct"}
        row["disk_pct"] = self._disk_pct
        peak = round(self._cpu_peak, 2)
        # El acumulador se vacia ANTES del await. Si se reseteara despues, las
        # muestras que el tick rapido va anadiendo mientras SQLite escribe
        # entrarian en el acumulador viejo y se descartarian sin guardarse.
        self.reset()
        try:
            await db.execute(
                "INSERT OR REPLACE INTO samples"
                " (ts, cpu_pct, cpu_peak, temp_c, freq_mhz, mem_pct, mem_used,"
                "  mem_total, swap_pct, net_rx, net_tx, disk_pct, load1)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, row["cpu_pct"], peak, row["temp_c"],
                 row["freq_mhz"], row["mem_pct"], row["mem_used"], row["mem_total"],
                 row["swap_pct"], row["net_rx"], row["net_tx"], row["disk_pct"],
                 row["load1"]),
            )
        except Exception:
            log.exception("no se pudo escribir la muestra del historico")
            return False
        return True


async def query_range(minutes: int, max_points: int = 600) -> dict[str, Any]:
    """Devuelve el historico de los ultimos `minutes`, submuestreado.

    Enviar 1440 puntos al navegador para un rango de 24 h no aporta nada visible
    y multiplica el trabajo de Chart.js, asi que se agrupa en cubos.
    """
    minutes = max(1, min(minutes, 60 * 24 * 31))
    since = int(time.time()) - minutes * 60
    # Se redondea el cubo HACIA ARRIBA al minuto. Truncando, un rango de 24 h
    # con max_points=600 daba cubos de 120 s y 720 puntos: mas de los pedidos.
    buckets_needed = -(-minutes // max(1, max_points))
    bucket = max(60, buckets_needed * 60)

    rows = await db.fetch_all(
        "SELECT (ts / ?) * ? AS ts,"
        "       AVG(cpu_pct) AS cpu_pct, MAX(cpu_peak) AS cpu_peak,"
        "       AVG(temp_c) AS temp_c, AVG(freq_mhz) AS freq_mhz,"
        "       AVG(mem_pct) AS mem_pct, AVG(mem_used) AS mem_used,"
        "       MAX(mem_total) AS mem_total, AVG(swap_pct) AS swap_pct,"
        "       AVG(net_rx) AS net_rx, AVG(net_tx) AS net_tx,"
        "       AVG(disk_pct) AS disk_pct, AVG(load1) AS load1"
        " FROM samples WHERE ts >= ?"
        " GROUP BY ts / ? ORDER BY ts ASC",
        (bucket, bucket, since, bucket),
    )
    for row in rows:
        for key, value in row.items():
            if isinstance(value, float):
                row[key] = round(value, 2)
    return {"minutes": minutes, "bucket_seconds": bucket, "points": len(rows), "series": rows}


aggregator = HistoryAggregator()
