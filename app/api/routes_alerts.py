"""CRUD de umbrales, historial de disparos y prueba de sinks."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Path, Query, Request

from ..alerts.engine import engine
from ..alerts.rules import METRIC_LABELS, RuleIn
from ..alerts.sinks import SINKS
from ..core.security import RequireUser
from ..storage.db import db
from .routes_auth import client_ip

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/rules")
async def list_rules(user: str = RequireUser) -> dict:
    return {
        "rules": engine.status(),
        "metrics": METRIC_LABELS,
        # Que sinks estan realmente utilizables, para que la UI pueda
        # deshabilitar los que no tienen configuracion en el entorno.
        "sinks": {name: sink.available() for name, sink in SINKS.items()},
    }


@router.post("/rules", status_code=201)
async def create_rule(rule: RuleIn, request: Request, user: str = RequireUser) -> dict:
    rule_id = await engine.create(rule)
    await db.audit(user, client_ip(request), "alert_rule_create", f"{rule_id}: {rule.name}")
    return {"ok": True, "id": rule_id}


@router.put("/rules/{rule_id}")
async def update_rule(rule: RuleIn, request: Request, rule_id: int = Path(ge=1),
                      user: str = RequireUser) -> dict:
    if not await engine.update(rule_id, rule):
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    await db.audit(user, client_ip(request), "alert_rule_update", f"{rule_id}: {rule.name}")
    return {"ok": True}


@router.delete("/rules/{rule_id}")
async def delete_rule(request: Request, rule_id: int = Path(ge=1),
                      user: str = RequireUser) -> dict:
    if not await engine.delete(rule_id):
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    await db.audit(user, client_ip(request), "alert_rule_delete", str(rule_id))
    return {"ok": True}


@router.get("/events")
async def list_events(limit: int = Query(default=50, ge=1, le=500),
                      user: str = RequireUser) -> dict:
    rows = await db.fetch_all(
        "SELECT * FROM alert_events ORDER BY ts DESC LIMIT ?", (limit,))
    for row in rows:
        try:
            row["delivery"] = json.loads(row["delivery"] or "{}")
        except json.JSONDecodeError:
            row["delivery"] = {}
    return {"events": rows}


@router.post("/test/{sink}")
async def test_sink(request: Request, sink: str = Path(min_length=1),
                    user: str = RequireUser) -> dict:
    result = await engine.test_sink(sink)
    await db.audit(user, client_ip(request), "alert_test", f"{sink}: {result['detail']}",
                   ok=result["ok"])
    return result


@router.get("/audit")
async def audit_log(limit: int = Query(default=50, ge=1, le=500),
                    user: str = RequireUser) -> dict:
    return {"entries": await db.fetch_all(
        "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,))}
