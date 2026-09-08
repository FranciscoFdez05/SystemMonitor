"""Autenticacion: hash Argon2, JWT en cookie httpOnly y freno a la fuerza bruta."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
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


def _expected_hash() -> str:
    if settings.password_hash:
        return settings.password_hash
    if settings.password:
        # Hashear en cada arranque cuesta una vez y evita guardar la clave en claro.
        return hash_password(settings.password)
    raise RuntimeError(
        "No hay credenciales: define SM_PASSWORD o SM_PASSWORD_HASH en el entorno")


_password_hash = _expected_hash()


def verify_credentials(username: str, password: str) -> bool:
    # La comparacion de usuario tambien pasa por Argon2 para no filtrar por
    # tiempo si el nombre de usuario existe o no.
    ok_user = username == settings.username
    try:
        _hasher.verify(_password_hash, password)
        ok_pass = True
    except (VerifyMismatchError, InvalidHashError):
        ok_pass = False
    return ok_user and ok_pass


def create_token(username: str) -> tuple[str, int]:
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    payload = {"sub": username, "exp": expires, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, _secret, algorithm=ALGORITHM), int(expires.timestamp())


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


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
