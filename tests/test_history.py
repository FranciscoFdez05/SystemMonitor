"""Agregacion del historico y submuestreo de las consultas."""
from __future__ import annotations

import pytest

from app.storage import history as history_module
from app.storage.history import HistoryAggregator


def sample(cpu: float, mem: float = 50.0) -> dict:
    return {
        "cpu": {"percent": cpu, "freq_mhz": 1500, "load": [0.5, 0.4, 0.3]},
        "memory": {"percent": mem, "used": 100, "total": 200, "swap_percent": 0},
        "thermal": {"temp_c": 45.0},
        "network": {"rx_bps": 1000, "tx_bps": 500},
    }


def test_average_and_peak_are_kept_separately():
    aggregator = HistoryAggregator()
    aggregator.add(sample(cpu=10))
    aggregator.add(sample(cpu=90))
    assert aggregator._average("cpu_pct") == 50.0
    # El pico se guarda aparte porque promediando desapareceria, y suele ser
    # justo lo que se busca al mirar hacia atras.
    assert aggregator._cpu_peak == 90


@pytest.mark.asyncio
async def test_flush_keeps_samples_that_arrive_while_writing(monkeypatch):
    """Regresion: el acumulador debe vaciarse ANTES de escribir en SQLite.

    Si se reseteara despues del await, las muestras que el tick rapido va
    anadiendo durante la escritura se descartarian sin llegar nunca al disco.
    """
    aggregator = HistoryAggregator()
    aggregator.add(sample(cpu=10))

    async def execute_while_a_sample_arrives(sql, params=()):
        aggregator.add(sample(cpu=90))
        return 1

    monkeypatch.setattr(history_module.db, "execute", execute_while_a_sample_arrives)
    assert await aggregator.flush() is True

    assert aggregator.has_data(), "la muestra recibida durante la escritura se perdio"
    assert aggregator._average("cpu_pct") == 90


@pytest.mark.asyncio
async def test_flush_on_an_empty_aggregator_is_a_noop():
    assert await HistoryAggregator().flush() is False


def test_disk_comes_from_the_slow_tick():
    aggregator = HistoryAggregator()
    aggregator.add(sample(cpu=10))
    aggregator.set_disk(73.5)
    assert aggregator._disk_pct == 73.5
    # Un valor ausente no debe borrar el ultimo conocido.
    aggregator.set_disk(None)
    assert aggregator._disk_pct == 73.5


def test_history_never_returns_more_points_than_asked(auth_client):
    """Regresion: truncando el cubo, 24 h con max_points=600 daba 720 puntos."""
    body = auth_client.get("/api/metrics/history?minutes=1440&max_points=600").json()
    assert 1440 * 60 / body["bucket_seconds"] <= 600


def test_history_never_buckets_below_a_minute(auth_client):
    """Un cubo menor que el intervalo de escritura no anadiria resolucion."""
    body = auth_client.get("/api/metrics/history?minutes=10&max_points=5000").json()
    assert body["bucket_seconds"] >= 60
