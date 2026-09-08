"""Middlewares de endurecimiento HTTP.

Dos protecciones que importan justo en el escenario de este panel: un servicio
sin TLS, con sesion por cookie, expuesto en la red local.
"""
from __future__ import annotations

import ipaddress
import logging
import socket

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from ..config import settings

log = logging.getLogger(__name__)

# script-src 'self' es lo que impide que un XSS llegue a ejecutar codigo.
# style-src necesita 'unsafe-inline' porque el dashboard usa atributos style
# para el ancho de las barras, que cambia en cada tick.
# connect-src incluye ws:/wss: en vez de fiarse de que el navegador trate el
# WebSocket como 'self': si esa interpretacion falla, el panel se queda sin
# datos en vivo, y el riesgo que queda ya lo cubre script-src.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    # frame-ancestors ya lo cubre en navegadores modernos; esto es el respaldo.
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname.strip("[]"))
        return True
    except ValueError:
        return False


class HostCheckMiddleware(BaseHTTPMiddleware):
    """Rechaza cabeceras Host que no correspondan a este equipo.

    Sin esto el panel es vulnerable a DNS rebinding: una web maliciosa que
    visites desde cualquier equipo de la red puede hacer que su dominio pase a
    resolver a la IP de la Pi y, a partir de ahi, hablar con el panel como si
    fuera mismo origen, con tu cookie de sesion incluida.

    El ataque necesita un *nombre de dominio*; entrando por IP no hay nada que
    rebindear. Por eso el criterio por defecto acepta IP, localhost y los
    nombres locales de LAN, y rechaza cualquier otro dominio salvo que se
    liste en SM_ALLOWED_HOSTS.
    """

    LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal")

    def __init__(self, app) -> None:
        super().__init__(app)
        self.extra = set(settings.allowed_host_list)
        self.disabled = "*" in self.extra
        self.own_hostname = socket.gethostname().lower()
        if self.disabled:
            log.warning("comprobacion de cabecera Host desactivada (SM_ALLOWED_HOSTS=*)")

    def allowed(self, hostname: str) -> bool:
        if self.disabled or not hostname:
            return True
        if hostname in self.extra:
            return True
        if hostname in ("localhost", self.own_hostname):
            return True
        if _is_ip_literal(hostname):
            return True
        return hostname.endswith(self.LOCAL_SUFFIXES)

    async def dispatch(self, request: Request, call_next) -> Response:
        # El puerto no forma parte de la decision; se descarta antes de mirar.
        host = request.headers.get("host", "").split(":")[0].strip().lower()
        if not self.allowed(host):
            log.warning("cabecera Host rechazada: %r", host)
            return PlainTextResponse(
                f"Host no permitido: {host}. Accede por IP, o anadelo a "
                "SM_ALLOWED_HOSTS.",
                status_code=400,
            )
        return await call_next(request)


def origin_is_same_site(headers) -> bool:
    """Valida el Origin del handshake de un WebSocket.

    Los WebSockets no pasan por CORS: cualquier web puede abrir uno contra
    este panel y el navegador adjuntara la cookie de sesion (*cross-site
    WebSocket hijacking*). La defensa es comparar Origin con Host.

    Un middleware HTTP no sirve aqui: BaseHTTPMiddleware solo ve peticiones
    con scope "http", nunca "websocket".

    Sin cabecera Origin se acepta: eso es un cliente que no es navegador
    (curl, un script), y ese ya ha tenido que presentar cookie o token.
    """
    origin = headers.get("origin")
    if not origin:
        return True
    host = headers.get("host", "").strip().lower()
    origin_host = origin.split("//", 1)[-1].strip().lower().rstrip("/")
    # Se comparan host y puerto: un servicio distinto en otro puerto del mismo
    # equipo es un origen distinto a todos los efectos.
    return origin_host == host
