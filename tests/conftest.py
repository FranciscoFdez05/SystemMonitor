"""Configuracion comun de los tests.

Las variables de entorno se fijan ANTES de importar nada de `app`: la
configuracion es un singleton que se construye al importar el modulo, asi que
tocarla despues no tendria efecto.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP_DB = Path(tempfile.mkdtemp(prefix="systemmonitor-tests-")) / "history.db"

os.environ.update({
    "SM_DB_PATH": str(TMP_DB),
    "SM_USERNAME": "tester",
    "SM_PASSWORD": "secreto-de-prueba",
    # 32+ bytes: por debajo, PyJWT avisa de clave HMAC corta.
    "SM_SECRET_KEY": "clave-fija-para-los-tests-de-systemmonitor",
    "SM_FAST_INTERVAL": "0.5",
    "SM_SLOW_INTERVAL": "0.5",
    "SM_PERSIST_INTERVAL": "3600",
    "SM_RETENTION_DAYS": "1",
    "SM_LOGIN_MAX_ATTEMPTS": "3",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    # El context manager dispara el lifespan: base de datos, reglas por
    # defecto y scheduler quedan arrancados como en produccion.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client):
    response = client.post("/api/login",
                           json={"username": "tester", "password": "secreto-de-prueba"})
    assert response.status_code == 200
    return client
