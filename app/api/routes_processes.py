"""Listado de procesos y terminacion controlada.

El orden de la tabla se hace en el navegador sobre los datos ya recibidos: no
tiene sentido ir al servidor para reordenar 120 filas que ya estan en memoria.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query, Request

from ..core.hub import hub
from ..core.security import RequireUser
from ..metrics.processes import KillError, kill_process
from ..metrics.registry import registry
from ..storage.db import db
from .routes_auth import client_ip

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/processes", tags=["processes"])


@router.get("")
async def list_processes(user: str = RequireUser) -> dict:
    return await registry.processes.acollect()


@router.delete("/{pid}")
async def kill(
    request: Request,
    pid: int = Path(ge=2),
    force: bool = Query(default=False, description="Usar SIGKILL en vez de SIGTERM"),
    user: str = RequireUser,
) -> dict:
    ip = client_ip(request)
    try:
        result = kill_process(pid, force=force)
    except KillError as exc:
        await db.audit(user, ip, "kill", f"pid={pid} rechazado: {exc}", ok=False)
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    await db.audit(user, ip, "kill",
                   f"pid={pid} name={result['name']} signal={result['signal']} "
                   f"terminado={result['terminated']}")
    # Se avisa a las demas pestanas abiertas: una tabla que sigue mostrando un
    # proceso ya muerto invita a intentar matarlo otra vez.
    hub.broadcast_event("process_killed", {**result, "by": user})
    return {"ok": True, **result}
