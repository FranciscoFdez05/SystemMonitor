"""Snapshot puntual e historico.

El camino normal para datos en vivo es el WebSocket; estos endpoints existen
para la carga inicial de la pagina, para el historico y para automatizar cosas
con curl sin abrir un WebSocket.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..core.scheduler import scheduler
from ..core.security import RequireUser
from ..metrics.registry import registry
from ..storage import retention
from ..storage.history import query_range

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/now")
async def now(user: str = RequireUser) -> dict:
    """Ultimo snapshot del scheduler; no vuelve a muestrear."""
    return scheduler.snapshot()


@router.get("/live")
async def live(user: str = RequireUser) -> dict:
    """Fuerza un muestreo completo. Util para depurar, caro para consultar en bucle."""
    return await registry.full_snapshot()


@router.get("/history")
async def history(
    minutes: int = Query(default=1440, ge=1, le=44640),
    max_points: int = Query(default=600, ge=10, le=5000),
    user: str = RequireUser,
) -> dict:
    return await query_range(minutes, max_points)


@router.get("/storage")
async def storage_stats(user: str = RequireUser) -> dict:
    """Cuanto ocupa el propio historico: el monitor tambien se vigila a si mismo."""
    return await retention.stats()
