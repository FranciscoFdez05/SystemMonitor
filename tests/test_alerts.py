"""Comportamiento del motor de alertas.

Lo que se prueba es justo lo que distingue un motor util de uno que genera
ruido: no disparar por un pico corto, no repetir mientras dura el problema y no
oscilar alrededor del umbral.
"""
from __future__ import annotations

import time

import pytest

from app.alerts.engine import HYSTERESIS, AlertEngine, RuleState
from app.alerts.rules import Rule


def make_rule(**overrides) -> Rule:
    base = dict(id=1, name="prueba", metric="cpu", target="", operator="gt",
                threshold=90.0, duration_s=60, cooldown_s=900, sinks=["log"],
                enabled=True, created_at=0)
    base.update(overrides)
    return Rule(**base)


@pytest.fixture
def engine(monkeypatch):
    instance = AlertEngine()
    emitted: list[tuple[str, float]] = []

    async def fake_emit(rule, value, state):
        emitted.append((state, value))

    monkeypatch.setattr(instance, "_emit", fake_emit)
    instance.emitted = emitted
    return instance


async def feed(engine, value, *, seconds_ago=0.0):
    engine.rules = engine.rules or []
    await engine.evaluate({"cpu": {"percent": value}})


@pytest.mark.asyncio
async def test_short_spike_does_not_fire(engine):
    engine.rules = [make_rule(duration_s=60)]
    await engine.evaluate({"cpu": {"percent": 99}})
    await engine.evaluate({"cpu": {"percent": 40}})
    assert engine.emitted == []


@pytest.mark.asyncio
async def test_fires_after_duration_held(engine):
    rule = make_rule(duration_s=60)
    engine.rules = [rule]
    await engine.evaluate({"cpu": {"percent": 95}})
    # Se retrasa el inicio del incumplimiento en vez de dormir 60 s reales.
    engine.states[rule.id].breaching_since = time.time() - 61
    await engine.evaluate({"cpu": {"percent": 95}})
    assert engine.emitted == [("firing", 95)]


@pytest.mark.asyncio
async def test_does_not_repeat_while_firing(engine):
    rule = make_rule(duration_s=0)
    engine.rules = [rule]
    for _ in range(5):
        await engine.evaluate({"cpu": {"percent": 95}})
    assert engine.emitted == [("firing", 95)]


@pytest.mark.asyncio
async def test_hysteresis_keeps_it_firing_just_below_threshold(engine):
    rule = make_rule(duration_s=0, threshold=90)
    engine.rules = [rule]
    await engine.evaluate({"cpu": {"percent": 95}})
    # 88 esta por debajo del umbral pero dentro del margen de histeresis:
    # la alerta sigue activa y no se emite un "resuelta" prematuro.
    await engine.evaluate({"cpu": {"percent": 90 - HYSTERESIS + 1}})
    assert engine.emitted == [("firing", 95)]
    assert engine.states[rule.id].firing


@pytest.mark.asyncio
async def test_resolves_once_clearly_below(engine):
    rule = make_rule(duration_s=0, threshold=90)
    engine.rules = [rule]
    await engine.evaluate({"cpu": {"percent": 95}})
    await engine.evaluate({"cpu": {"percent": 50}})
    assert engine.emitted == [("firing", 95), ("resolved", 50)]


@pytest.mark.asyncio
async def test_cooldown_blocks_immediate_refire(engine):
    rule = make_rule(duration_s=0, cooldown_s=900)
    engine.rules = [rule]
    await engine.evaluate({"cpu": {"percent": 95}})
    await engine.evaluate({"cpu": {"percent": 50}})   # resuelve
    await engine.evaluate({"cpu": {"percent": 95}})   # vuelve a incumplir
    assert [state for state, _ in engine.emitted] == ["firing", "resolved"]


@pytest.mark.asyncio
async def test_missing_metric_is_neither_firing_nor_resolved(engine):
    """Sin sensor termico no se puede afirmar nada: no se emite evento."""
    rule = make_rule(metric="temperature", duration_s=0)
    engine.rules = [rule]
    engine.states[rule.id] = RuleState(firing=True)
    await engine.evaluate({"thermal": {"temp_c": None}})
    assert engine.emitted == []
    assert engine.states[rule.id].firing


@pytest.mark.asyncio
async def test_disk_rule_targets_a_mountpoint(engine):
    rule = make_rule(metric="disk", target="/data", duration_s=0, threshold=80)
    engine.rules = [rule]
    await engine.evaluate({"disk": {"partitions": [
        {"mount": "/", "percent": 99},
        {"mount": "/data", "percent": 85},
    ]}})
    assert engine.emitted == [("firing", 85)]


def test_lt_operator_relaxes_upwards():
    """Con "menor que", la histeresis debe subir el umbral, no bajarlo."""
    engine = AlertEngine()
    rule = make_rule(operator="lt", threshold=10)
    assert engine._breaching(rule, 9, currently_firing=False)
    assert engine._breaching(rule, 12, currently_firing=True)
    assert not engine._breaching(rule, 12, currently_firing=False)
