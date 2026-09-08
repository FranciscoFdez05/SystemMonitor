"""Health check publico.

Deliberadamente sin autenticacion: sirve para que Docker, systemd o un
monitor externo comprueben el proceso, y no expone ninguna metrica del
sistema, solo si el propio servicio funciona.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Response, status

from ..core.scheduler import scheduler
from ..metrics.system import APP_START
from ..storage.db import db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response) -> dict:
    scheduler_health = scheduler.health()
    db_ok = await db.healthy()
    # Un proceso vivo cuyo bucle de muestreo se ha parado esta roto aunque
    # responda: por eso 'stalled' cuenta como fallo.
    ok = db_ok and scheduler_health["running"] and not scheduler_health["stalled"]
    response.status_code = (status.HTTP_200_OK if ok
                            else status.HTTP_503_SERVICE_UNAVAILABLE)
    return {
        "status": "ok" if ok else "degraded",
        "uptime_seconds": int(time.time() - APP_START),
        "database": "ok" if db_ok else "error",
        "scheduler": scheduler_health,
    }
