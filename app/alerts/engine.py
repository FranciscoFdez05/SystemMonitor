"""Evaluacion de reglas con histeresis, duracion minima y cooldown.

Los tres mecanismos existen para el mismo problema: sin ellos una metrica que
oscila alrededor del umbral genera una tormenta de notificaciones y se acaba
ignorando el canal entero.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from ..storage.db import db, dumps
from .rules import DEFAULT_RULES, Rule, RuleIn
from .sinks import SINKS

log = logging.getLogger(__name__)

# Margen para desactivar: una regla que salta a 90 no se resuelve hasta bajar
# de 87. Sin este margen, oscilar entre 89.9 y 90.1 dispara sin parar.
HYSTERESIS = 3.0


@dataclass
class RuleState:
    breaching_since: float | None = None
    firing: bool = False
    last_fired: float = 0.0
    last_value: float | None = None


@dataclass
class AlertEngine:
    rules: list[Rule] = field(default_factory=list)
    states: dict[int, RuleState] = field(default_factory=dict)
    recent: list[dict[str, Any]] = field(default_factory=list)
    hostname: str = field(default_factory=socket.gethostname)
    _broadcast: Any = None

    def set_broadcaster(self, callback: Any) -> None:
        """El motor no conoce el hub: recibe una funcion para publicar eventos."""
        self._broadcast = callback

    # ---------------------------------------------------------------- reglas
    async def load(self) -> None:
        rows = await db.fetch_all("SELECT * FROM alert_rules ORDER BY id")
        if not rows:
            for rule in DEFAULT_RULES:
                await self.create(rule)
            rows = await db.fetch_all("SELECT * FROM alert_rules ORDER BY id")
        self.rules = [Rule.from_row(row) for row in rows]
        # Se conserva el estado de las reglas que siguen existiendo para no
        # reiniciar los contadores de duracion en cada recarga.
        self.states = {r.id: self.states.get(r.id, RuleState()) for r in self.rules}
        log.info("%d reglas de alerta cargadas", len(self.rules))

    async def create(self, rule: RuleIn) -> int:
        rule_id = await db.execute(
            "INSERT INTO alert_rules (name, metric, target, operator, threshold,"
            " duration_s, cooldown_s, sinks, enabled, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rule.name, rule.metric, rule.target, rule.operator, rule.threshold,
             rule.duration_s, rule.cooldown_s, ",".join(rule.sinks),
             int(rule.enabled), int(time.time())),
        )
        await self.load()
        return rule_id

    async def update(self, rule_id: int, rule: RuleIn) -> bool:
        existing = await db.fetch_one("SELECT id FROM alert_rules WHERE id = ?", (rule_id,))
        if not existing:
            return False
        await db.execute(
            "UPDATE alert_rules SET name=?, metric=?, target=?, operator=?, threshold=?,"
            " duration_s=?, cooldown_s=?, sinks=?, enabled=? WHERE id=?",
            (rule.name, rule.metric, rule.target, rule.operator, rule.threshold,
             rule.duration_s, rule.cooldown_s, ",".join(rule.sinks),
             int(rule.enabled), rule_id),
        )
        await self.load()
        return True

    async def delete(self, rule_id: int) -> bool:
        existing = await db.fetch_one("SELECT id FROM alert_rules WHERE id = ?", (rule_id,))
        if not existing:
            return False
        await db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
        self.states.pop(rule_id, None)
        await self.load()
        return True

    # ------------------------------------------------------------ evaluacion
    @staticmethod
    def extract(rule: Rule, snapshot: dict[str, Any]) -> float | None:
        cpu = snapshot.get("cpu") or {}
        memory = snapshot.get("memory") or {}
        thermal = snapshot.get("thermal") or {}
        disk = snapshot.get("disk") or {}

        if rule.metric == "cpu":
            return cpu.get("percent")
        if rule.metric == "load":
            return cpu.get("load_percent")
        if rule.metric == "memory":
            return memory.get("percent")
        if rule.metric == "swap":
            return memory.get("swap_percent")
        if rule.metric == "temperature":
            return thermal.get("temp_c")
        if rule.metric == "disk":
            wanted = rule.target or "/"
            for partition in disk.get("partitions", []):
                if partition["mount"] == wanted:
                    return partition["percent"]
            return None
        return None

    def _breaching(self, rule: Rule, value: float, currently_firing: bool) -> bool:
        threshold = rule.threshold
        if currently_firing:
            # Umbral relajado mientras la alerta esta activa: es la histeresis.
            threshold = (threshold - HYSTERESIS if rule.operator == "gt"
                         else threshold + HYSTERESIS)
        return value > threshold if rule.operator == "gt" else value < threshold

    async def evaluate(self, snapshot: dict[str, Any]) -> None:
        now = time.time()
        for rule in self.rules:
            if not rule.enabled:
                continue
            state = self.states.setdefault(rule.id, RuleState())
            value = self.extract(rule, snapshot)
            if value is None:
                # Metrica no disponible (p.ej. sin sensor termico): no se puede
                # afirmar ni que incumple ni que se ha resuelto.
                continue
            state.last_value = value

            if self._breaching(rule, value, state.firing):
                if state.breaching_since is None:
                    state.breaching_since = now
                held = now - state.breaching_since
                cooled = (now - state.last_fired) >= rule.cooldown_s
                if not state.firing and held >= rule.duration_s and cooled:
                    state.firing = True
                    state.last_fired = now
                    await self._emit(rule, value, "firing")
            else:
                if state.firing:
                    state.firing = False
                    await self._emit(rule, value, "resolved")
                state.breaching_since = None

    async def _emit(self, rule: Rule, value: float, state: str) -> None:
        event = {
            "ts": int(time.time()),
            "host": self.hostname,
            "rule_id": rule.id,
            "rule_name": rule.name,
            "metric": rule.metric,
            "target": rule.target,
            "operator": rule.operator,
            "value": round(value, 2),
            "threshold": rule.threshold,
            "state": state,
        }

        delivery: dict[str, str] = {}
        for name in rule.sinks:
            sink = SINKS.get(name)
            if sink is None:
                delivery[name] = "sink desconocido"
                continue
            if not sink.available():
                delivery[name] = "no configurado"
                continue
            try:
                delivery[name] = await sink.send(event)
            except Exception as exc:
                # Un webhook caido no debe tumbar el bucle de metricas.
                delivery[name] = f"error: {exc.__class__.__name__}"
                log.warning("sink %s fallo para la regla %s: %s", name, rule.name, exc)

        event["delivery"] = delivery
        self.recent.insert(0, event)
        del self.recent[50:]

        try:
            await db.execute(
                "INSERT INTO alert_events (ts, rule_id, rule_name, metric, target,"
                " value, threshold, state, delivery) VALUES (?,?,?,?,?,?,?,?,?)",
                (event["ts"], rule.id, rule.name, rule.metric, rule.target,
                 event["value"], rule.threshold, state, dumps(delivery)),
            )
        except Exception:
            log.exception("no se pudo registrar el evento de alerta")

        if self._broadcast:
            self._broadcast("alert", event)

    async def test_sink(self, name: str) -> dict[str, Any]:
        sink = SINKS.get(name)
        if sink is None:
            return {"ok": False, "detail": "sink desconocido"}
        if not sink.available():
            return {"ok": False, "detail": "sink sin configurar (revisa el .env)"}
        event = {
            "ts": int(time.time()), "host": self.hostname, "rule_id": 0,
            "rule_name": "Prueba de configuracion", "metric": "cpu", "target": "",
            "operator": "gt", "value": 0, "threshold": 0, "state": "firing",
        }
        try:
            return {"ok": True, "detail": await asyncio.wait_for(sink.send(event), 10)}
        except Exception as exc:
            return {"ok": False, "detail": f"{exc.__class__.__name__}: {exc}"}

    def status(self) -> list[dict[str, Any]]:
        out = []
        for rule in self.rules:
            state = self.states.get(rule.id, RuleState())
            out.append({
                **rule.model_dump(),
                "description": rule.describe(),
                "firing": state.firing,
                "value": state.last_value,
                "breaching_since": state.breaching_since,
            })
        return out


engine = AlertEngine()
