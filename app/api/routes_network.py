"""Conexiones activas y ancho de banda."""
from __future__ import annotations

from fastapi import APIRouter

from ..core.scheduler import scheduler
from ..core.security import RequireUser
from ..metrics.registry import registry

router = APIRouter(prefix="/api/network", tags=["network"])


@router.get("/connections")
async def connections(user: str = RequireUser) -> dict:
    return await registry.connections.acollect()


@router.get("/bandwidth")
async def bandwidth(user: str = RequireUser) -> dict:
    return scheduler.last_fast.get("network", {})
