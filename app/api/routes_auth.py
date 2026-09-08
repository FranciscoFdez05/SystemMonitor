"""Login, logout e identidad de la sesion."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..config import settings
from ..core.security import (
    COOKIE_NAME,
    RequireUser,
    create_token,
    revoke_token,
    throttle,
    verify_credentials,
)
from ..storage.db import db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def client_ip(request: Request) -> str:
    # Sin proxy inverso delante, client.host es la IP real de la LAN. No se
    # confia en X-Forwarded-For: cualquiera podria falsearla para saltarse el
    # bloqueo por intentos.
    return request.client.host if request.client else "?"


@router.post("/login")
async def login(payload: LoginIn, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    locked = throttle.locked_for(ip)
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Reintenta en {locked} s.",
        )

    if not verify_credentials(payload.username, payload.password):
        throttle.record_failure(ip)
        # Retardo fijo para que un atacante no distinga por tiempo entre
        # usuario inexistente y contrasena incorrecta.
        await asyncio.sleep(0.5)
        await db.audit(payload.username, ip, "login", "credenciales invalidas", ok=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Usuario o contrasena incorrectos")

    throttle.record_success(ip)
    token, expires = create_token(payload.username)
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=settings.session_hours * 3600,
        httponly=True,          # inaccesible desde JS: limita el robo por XSS
        # Lax impide que la cookie viaje en peticiones POST/DELETE originadas
        # en otro sitio, que es la proteccion CSRF de este panel.
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    await db.audit(payload.username, ip, "login", "sesion iniciada")
    return {"ok": True, "username": payload.username, "expires": expires}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    # Borrar la cookie solo afecta a este navegador. Se invalida ademas el
    # token en el servidor para que una copia robada tampoco sirva.
    revoke_token(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: str = RequireUser) -> dict:
    return {"username": user}
