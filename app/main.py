"""Punto de entrada de la aplicacion."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .alerts.engine import engine
from .api import (
    routes_alerts,
    routes_auth,
    routes_health,
    routes_metrics,
    routes_network,
    routes_processes,
    ws,
)
from .config import BASE_DIR, settings
from .core.hardening import HostCheckMiddleware, SecurityHeadersMiddleware
from .core.scheduler import scheduler
from .core.security import COOKIE_NAME, decode_token
from .storage.db import db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("systemmonitor")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _warn_if_root() -> None:
    """Avisa si el monitor corre como root.

    Con pid: host y sin privilegios rebajados, un fallo en esta aplicacion es
    un fallo con permisos totales sobre el equipo. Merece una linea en el log
    cada arranque, no quedar escondido en la configuracion.
    """
    if hasattr(os, "getuid") and os.getuid() == 0:
        log.warning(
            "ejecutandose como root. El contenedor esta pensado para correr "
            "como usuario sin privilegios; revisa el despliegue.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_if_root()
    await db.connect()
    await engine.load()
    await scheduler.start()
    log.info("SystemMonitor escuchando en http://%s:%s", settings.host, settings.port)
    try:
        yield
    finally:
        await scheduler.stop()
        await db.close()


app = FastAPI(
    title="SystemMonitor",
    description="Panel de monitorizacion para Raspberry Pi",
    version="1.0.0",
    lifespan=lifespan,
    # La documentacion interactiva revelaria la superficie de la API sin login.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# El orden importa: el ultimo anadido es el primero que ve la peticion, asi
# que la comprobacion de Host va delante de todo lo demas.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(HostCheckMiddleware)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

for module in (routes_auth, routes_metrics, routes_processes, routes_network,
               routes_alerts, routes_health, ws):
    app.include_router(module.router)


def _logged_in(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    return bool(token and decode_token(token))


@app.get("/", include_in_schema=False)
async def dashboard(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "dashboard.html", {
        "fast_interval": settings.fast_interval,
        "slow_interval": settings.slow_interval,
    })


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    if _logged_in(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {})


def run() -> None:
    """Arranque directo: python -m app.main"""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        # Un solo worker a proposito: los colectores mantienen estado (contadores
        # previos para calcular tasas) y varios procesos multiplicarian el
        # muestreo sin aportar nada en una Pi.
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    run()
