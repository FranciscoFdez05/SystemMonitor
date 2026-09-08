"""Modelos de las reglas de alerta."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Metric = Literal["cpu", "memory", "swap", "disk", "temperature", "load"]
Operator = Literal["gt", "lt"]

VALID_SINKS = {"log", "webhook", "telegram", "discord"}

METRIC_LABELS = {
    "cpu": "Uso de CPU (%)",
    "memory": "Uso de RAM (%)",
    "swap": "Uso de swap (%)",
    "disk": "Ocupacion de disco (%)",
    "temperature": "Temperatura (C)",
    "load": "Carga normalizada (%)",
}


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    metric: Metric
    target: str = Field(default="", max_length=120)
    operator: Operator = "gt"
    threshold: float
    # Exigir que la condicion se mantenga evita alertas por un pico de 2 s.
    duration_s: int = Field(default=60, ge=0, le=86400)
    # Silencio tras disparar: sin esto un disco lleno notifica cada minuto.
    cooldown_s: int = Field(default=900, ge=0, le=86400)
    sinks: list[str] = Field(default_factory=lambda: ["log"])
    enabled: bool = True

    @field_validator("sinks")
    @classmethod
    def _check_sinks(cls, value: list[str]) -> list[str]:
        unknown = set(value) - VALID_SINKS
        if unknown:
            raise ValueError(f"sinks desconocidos: {', '.join(sorted(unknown))}")
        return value or ["log"]


class Rule(RuleIn):
    id: int
    created_at: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Rule":
        return cls(
            id=row["id"], name=row["name"], metric=row["metric"], target=row["target"],
            operator=row["operator"], threshold=row["threshold"],
            duration_s=row["duration_s"], cooldown_s=row["cooldown_s"],
            sinks=[s for s in (row["sinks"] or "").split(",") if s],
            enabled=bool(row["enabled"]), created_at=row["created_at"],
        )

    def describe(self) -> str:
        symbol = ">" if self.operator == "gt" else "<"
        target = f" [{self.target}]" if self.target else ""
        return f"{METRIC_LABELS.get(self.metric, self.metric)}{target} {symbol} {self.threshold}"


DEFAULT_RULES: list[RuleIn] = [
    RuleIn(name="CPU alta sostenida", metric="cpu", threshold=90, duration_s=300),
    RuleIn(name="RAM casi llena", metric="memory", threshold=90, duration_s=300),
    RuleIn(name="Disco raiz al 90%", metric="disk", target="/", threshold=90, duration_s=60),
    RuleIn(name="Temperatura critica", metric="temperature", threshold=80, duration_s=60),
]
