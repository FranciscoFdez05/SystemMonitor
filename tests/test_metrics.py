"""La capa de metricas debe devolver estructuras coherentes en cualquier host.

No se comprueban valores concretos (dependen de la maquina) sino el contrato:
claves presentes, tipos y rangos plausibles.
"""
from __future__ import annotations

import asyncio

import pytest

from app.metrics.base import RateTracker
from app.metrics.registry import registry


def test_cpu_contract():
    data = registry.cpu.collect()
    assert 0 <= data["percent"] <= 100
    assert len(data["per_core"]) == data["cores_logical"]
    assert all(0 <= core <= 100 for core in data["per_core"])
    assert len(data["load"]) == 3


def test_memory_contract():
    data = registry.memory.collect()
    assert data["total"] > 0
    assert data["used"] + data["available"] == pytest.approx(data["total"], rel=0.01)
    assert 0 <= data["percent"] <= 100


def test_disk_reports_at_least_one_partition():
    data = registry.disk.collect()
    assert data["partitions"], "deberia detectarse al menos una particion real"
    for partition in data["partitions"]:
        assert partition["total"] > 0
        assert partition["used"] + partition["free"] <= partition["total"] * 1.05
        assert partition["level"] in {"ok", "warning", "critical"}


def test_disk_level_thresholds():
    """El nivel critico es exactamente "menos del 10% libre"."""
    from app.metrics import disk as disk_module

    assert disk_module.LOW_SPACE_CRIT == 10.0
    assert disk_module.LOW_SPACE_WARN == 20.0


def test_thermal_contract():
    data = registry.thermal.collect()
    assert data["level"] in {"ok", "warning", "critical", "unknown"}
    if data["temp_c"] is not None:
        # Un sensor que reporta fuera de este rango esta mal escalado, que es
        # el error clasico al leer milicelsius como celsius.
        assert -20 < data["temp_c"] < 150


def test_system_uptimes():
    data = registry.system.collect()
    assert data["uptime_seconds"] >= 0
    assert data["app_uptime_seconds"] >= 0
    assert data["hostname"]


def test_processes_are_normalised_per_core():
    data = registry.processes.collect()
    assert data["total"] > 0
    for row in data["processes"]:
        # cpu esta normalizado por nucleo, cpu_raw es el valor bruto de psutil.
        assert 0 <= row["cpu"] <= 105
        assert row["pid"] > 0


def test_rate_tracker_needs_two_samples():
    tracker = RateTracker()
    assert tracker.update({"rx": 1000}) == {}
    rates = tracker.update({"rx": 2000})
    assert rates["rx"] > 0


def test_rate_tracker_discards_counter_resets():
    """Un contador que retrocede (interfaz reiniciada) no debe dar un pico."""
    tracker = RateTracker()
    tracker.update({"rx": 5000})
    assert "rx" not in tracker.update({"rx": 10})


def test_registry_snapshot_covers_every_channel():
    snapshot = asyncio.run(registry.full_snapshot())
    assert set(snapshot) == set(registry.all)
    assert not any(value.get("error") for value in snapshot.values())
