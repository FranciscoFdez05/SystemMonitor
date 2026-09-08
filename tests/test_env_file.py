"""El hash de la contraseña tiene que sobrevivir al viaje por el .env.

Un hash Argon2 empieza por `$argon2id$v=19$m=65536,...`. Los `$` son el riesgo:
un lector de .env que hiciera expansión de variables lo dejaría troceado,
`verify` lanzaría InvalidHashError y el panel respondería "usuario o contraseña
incorrectos" incluso a la contraseña correcta.

Lo que se comprueba aquí:
  - python-dotenv (la ruta nativa, sin Docker) NO expande nada, ni con comillas
    ni sin ellas. Esa ruta nunca estuvo rota.
  - Entrecomillar es una precaución para el lector de .env de Docker Compose,
    que no se puede ejercitar desde los tests. Lo que sí se comprueba es que
    entrecomillar no rompe nada y que el valor va y vuelve idéntico.
  - Y que el servidor distingue en su log las tres causas de un login
    rechazado, que desde fuera son la misma respuesta.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
HASH = ("$argon2id$v=19$m=65536,t=2,p=2$50RFvuUwO3UMSsEylz/qUQ"
        "$ajF5+j6lU4iCk3+qmPSb0WqToAo+JDvxqGceaFhcgJ0")


# ────────────────────────────── qué hace de verdad el lector de .env de Python
@pytest.mark.parametrize("linea", [
    f"SM_PASSWORD_HASH={HASH}\n",
    f"SM_PASSWORD_HASH='{HASH}'\n",
    f'SM_PASSWORD_HASH="{HASH}"\n',
])
def test_python_dotenv_never_mangles_the_hash(tmp_path, linea):
    """La instalación nativa lee el .env con python-dotenv y sale intacto.

    Se fija aquí porque es fácil suponer lo contrario: los `$` invitan a pensar
    que hay expansión, y no la hay. Si una versión futura la introdujera, este
    test lo diría antes de que nadie se quedase sin poder entrar.
    """
    (tmp_path / ".env").write_text(linea, encoding="utf-8")
    assert dotenv_values(tmp_path / ".env")["SM_PASSWORD_HASH"] == HASH


# ─────────────────────────────────── por qué el síntoma despista tanto
def test_a_broken_hash_is_reported_as_a_wrong_password():
    """Un hash inválido y una contraseña mala dan la misma respuesta HTTP.

    Por eso la comprobación que hacía docker-up.sh (pedir un login con
    contraseña incorrecta y esperar un 401) no servía: los dos casos son un
    401. Ahora el script compara el hash del .env con el que ve el contenedor,
    y el servidor distingue los dos motivos en su log.
    """
    with pytest.raises(InvalidHashError):
        PasswordHasher().verify("=19=65536,t=2,p=2$abc", "la-contrasena-correcta")


def test_the_server_log_tells_the_three_causes_apart(caplog, monkeypatch):
    from app.config import settings
    from app.core import security

    bueno = security.hash_password("secreta")
    monkeypatch.setattr(settings, "username", "francisco")

    with caplog.at_level(logging.WARNING, logger="app.core.security"):
        monkeypatch.setattr(settings, "password_hash", bueno)
        monkeypatch.setattr(security, "_password_hash", None)
        assert security.verify_credentials("francisco", "mala") is False
        assert "contrasena no coincide" in caplog.text

        caplog.clear()
        assert security.verify_credentials("otro", "secreta") is False
        assert "no coincide con SM_USERNAME" in caplog.text

        caplog.clear()
        monkeypatch.setattr(settings, "password_hash", "=19=65536,t=2,p=2$abc")
        monkeypatch.setattr(security, "_password_hash", None)
        assert security.verify_credentials("francisco", "secreta") is False
        assert "no es un hash Argon2 valido" in caplog.text


def test_correct_credentials_still_work(monkeypatch):
    from app.config import settings
    from app.core import security

    bueno = security.hash_password("secreta")
    monkeypatch.setattr(settings, "username", "francisco")
    monkeypatch.setattr(settings, "password_hash", bueno)
    monkeypatch.setattr(security, "_password_hash", None)
    assert security.verify_credentials("francisco", "secreta") is True


# ─────────────────────────────────── el escritor de .env de docker-up.sh
def _funciones_del_script() -> str:
    """Extrae env_get/env_set/migrar del script para probarlos de verdad."""
    fuente = (RAIZ / "docker-up.sh").read_text(encoding="utf-8")
    bloques = ["COMILLA=\"'\"\n"]
    for nombre in ("env_get", "env_set", "migrar_comillas_del_hash"):
        inicio = fuente.index(f"{nombre}() {{")
        fin = fuente.index("\n}\n", inicio) + 3
        bloques.append(fuente[inicio:fin])
    return "\n".join(bloques)


def _ejecutar_sh(script: str, cwd: Path, env_inicial: str = "") -> subprocess.CompletedProcess:
    """Ejecuta un fragmento de shell con las funciones reales del script.

    El .env de partida lo escribe Python, no el shell. Una línea como
    SM_PASSWORD_HASH='$argon2id$...' lleva comillas simples dentro; pasarla por
    printf obligaría a escaparla y el propio shell del test acabaría expandiendo
    los `$`, con lo que estaríamos probando otra cosa.
    """
    sh = shutil.which("sh") or shutil.which("bash")
    if sh is None:
        pytest.skip("no hay un shell POSIX en este equipo")
    if env_inicial:
        (cwd / ".env").write_text(env_inicial, encoding="utf-8")
    (cwd / "funcs.sh").write_text(_funciones_del_script(), encoding="utf-8")
    cabecera = textwrap.dedent("""
        set -e
        aviso() { printf 'AVISO %s\\n' "$*"; }
        error() { printf 'ERROR %s\\n' "$*"; }
        . ./funcs.sh
    """)
    (cwd / "prueba.sh").write_text(cabecera + script, encoding="utf-8")
    return subprocess.run([sh, "prueba.sh"], cwd=cwd, capture_output=True, text=True)


def test_env_set_quotes_a_value_containing_dollars(tmp_path):
    resultado = _ejecutar_sh(
        f"env_set SM_PASSWORD_HASH '{HASH}'\ncat .env\n",
        tmp_path, env_inicial="SM_USERNAME=admin\n")
    assert resultado.returncode == 0, resultado.stderr
    assert f"SM_PASSWORD_HASH='{HASH}'" in resultado.stdout


def test_env_set_leaves_plain_values_unquoted(tmp_path):
    """Un .env lleno de comillas innecesarias se edita peor a mano."""
    resultado = _ejecutar_sh(
        "env_set SM_PORT 9000\nenv_set SM_SECRET_KEY abc-DEF_123\ncat .env\n",
        tmp_path, env_inicial="SM_PORT=7000\n")
    assert resultado.returncode == 0, resultado.stderr
    assert "SM_PORT=9000" in resultado.stdout
    assert "SM_SECRET_KEY=abc-DEF_123" in resultado.stdout
    assert "'" not in resultado.stdout


def test_env_get_returns_the_value_without_quotes(tmp_path):
    resultado = _ejecutar_sh(
        "env_get SM_PASSWORD_HASH\n",
        tmp_path, env_inicial=f"SM_PASSWORD_HASH='{HASH}'\n")
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == HASH


def test_migration_quotes_an_env_written_by_the_old_script(tmp_path):
    """Actualizar el script no basta: el .env ya escrito sigue en la Pi."""
    resultado = _ejecutar_sh(
        "migrar_comillas_del_hash\ncat .env\n",
        tmp_path, env_inicial=f"SM_PASSWORD_HASH={HASH}\n")
    assert resultado.returncode == 0, resultado.stderr
    assert f"SM_PASSWORD_HASH='{HASH}'" in resultado.stdout


def test_migration_is_idempotent(tmp_path):
    resultado = _ejecutar_sh(
        "migrar_comillas_del_hash\nmigrar_comillas_del_hash\ncat .env\n",
        tmp_path, env_inicial=f"SM_PASSWORD_HASH='{HASH}'\n")
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.count("SM_PASSWORD_HASH=") == 1
    assert f"SM_PASSWORD_HASH='{HASH}'" in resultado.stdout


# ─────────────────────────────────── coherencia de la documentación
def test_the_example_env_shows_the_hash_quoted():
    ejemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert "SM_PASSWORD_HASH='$argon2id" in ejemplo


def test_hashpw_interactive_output_includes_the_quotes():
    fuente = (RAIZ / "app" / "tools" / "hashpw.py").read_text(encoding="utf-8")
    assert "SM_PASSWORD_HASH='{hash_password(password)}'" in fuente
