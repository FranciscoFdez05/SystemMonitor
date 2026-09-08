"""Autenticacion: hash Argon2, JWT en cookie httpOnly y freno a la fuerza bruta."""
from __future__ import annotations

import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status

from ..config import settings

log = logging.getLogger(__name__)

COOKIE_NAME = "sm_session"
ALGORITHM = "HS256"

# Parametros conservadores: en una Pi 4 un hash Argon2id con 64 MiB tarda
# ~0.3 s, suficiente contra fuerza bruta sin bloquear el login.
_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
_secret = settings.resolve_secret()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


MISSING_CREDENTIALS = (
    "No hay credenciales configuradas. Define SM_PASSWORD o SM_PASSWORD_HASH "
    "en el .env (o ejecuta ./docker-up.sh, que las pide en el primer arranque)."
)

_password_hash: str | None = None


def credentials_configured() -> bool:
    return bool(settings.password_hash or settings.password)


def expected_hash() -> str:
    """Hash contra el que se verifica el login, calculado una sola vez.

    Perezoso a proposito. Calcularlo al importar el modulo hacia imposible
    usar `python -m app.tools.hashpw`, que existe justo para cuando todavia no
    hay credenciales: importar la herramienta reventaba antes de poder generar
    el hash que le faltaba.
    """
    global _password_hash
    if _password_hash is None:
        if settings.password_hash:
            _password_hash = settings.password_hash
        elif settings.password:
            # Hashear una vez al primer login evita guardar la clave en claro.
            _password_hash = hash_password(settings.password)
        else:
            raise RuntimeError(MISSING_CREDENTIALS)
    return _password_hash


def verify_credentials(username: str, password: str) -> bool:
    # El hash se verifica SIEMPRE, aunque el usuario no coincida: si se
    # cortocircuitara, la respuesta seria instantanea para un usuario que no
    # existe y lenta para uno que si, revelando cual es el correcto.
    # compare_digest evita la misma fuga por el lado del nombre.
    ok_user = secrets.compare_digest(username.encode(), settings.username.encode())
    try:
        _hasher.verify(expected_hash(), password)
        ok_pass = True
    except (VerifyMismatchError, InvalidHashError):
        ok_pass = False
    return ok_user and ok_pass


# Identificadores de sesiones cerradas antes de que caducase su token. Sin
# esto, "Salir" solo borra la cookie del navegador: el token seguiria siendo
# valido durante horas para quien lo hubiera copiado.
_revoked: dict[str, int] = {}


def _purge_revoked(now: int) -> None:
    for jti, expires in list(_revoked.items()):
        if expires <= now:
            del _revoked[jti]


def create_token(username: str) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires = now + timedelta(hours=settings.session_hours)
    payload = {
        "sub": username,
        "exp": expires,
        "iat": now,
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, _secret, algorithm=ALGORITHM), int(expires.timestamp())


def revoke_token(token: str | None) -> None:
    payload = decode_token(token) if token else None
    if not payload or "jti" not in payload:
        return
    now = int(time.time())
    _purge_revoked(now)
    _revoked[payload["jti"]] = int(payload.get("exp", now))


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, _secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("jti") in _revoked:
        return None
    return payload


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def current_user(request: Request) -> str:
    """Dependencia para endpoints protegidos."""
    token = _token_from_request(request)
    payload = decode_token(token) if token else None
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesion no valida o caducada",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload["sub"]


RequireUser = Depends(current_user)


def user_from_websocket(cookies: dict[str, str], token_param: str | None) -> str | None:
    """Autentica el handshake del WebSocket.

    Los navegadores no permiten cabeceras personalizadas al abrir un WebSocket,
    asi que la cookie es el camino normal; el parametro token queda para
    clientes que no son navegador.
    """
    token = token_param or cookies.get(COOKIE_NAME)
    payload = decode_token(token) if token else None
    return payload["sub"] if payload else None


class LoginThrottle:
    """Bloqueo temporal por IP tras varios fallos consecutivos."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._blocked: dict[str, float] = {}

    def locked_for(self, ip: str) -> int:
        until = self._blocked.get(ip)
        if until is None:
            return 0
        remaining = int(until - time.monotonic())
        if remaining <= 0:
            self._blocked.pop(ip, None)
            self._failures.pop(ip, None)
            return 0
        return remaining

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        window = settings.login_lockout_seconds
        recent = [t for t in self._failures.get(ip, []) if now - t < window]
        recent.append(now)
        self._failures[ip] = recent
        if len(recent) >= settings.login_max_attempts:
            self._blocked[ip] = now + window
            log.warning("login bloqueado para %s tras %d fallos", ip, len(recent))

    def record_success(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._blocked.pop(ip, None)


throttle = LoginThrottle()
