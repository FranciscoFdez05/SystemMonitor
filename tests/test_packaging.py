"""Coherencia entre el código, los scripts de despliegue y el compose.

Nada de esto lo detectan los tests de la aplicación, pero cualquiera de estos
fallos rompe el despliegue en la Pi, no en el portátil de desarrollo.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = ["docker-up.sh", "docker-update.sh"]


def test_version_has_a_sane_format():
    from app.version import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_the_api_reports_the_same_version():
    from app.main import app
    from app.version import __version__

    assert app.version == __version__


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_deploy_scripts_read_the_version_the_same_way(script):
    """Los scripts sacan la versión con sed. Si cambia el formato de la línea,
    dejan de verla y la imagen se etiqueta como "latest", que es justo lo que
    deja a docker-update.sh sin vuelta atrás."""
    from app.version import __version__

    fuente = (RAIZ / "app" / "version.py").read_text(encoding="utf-8")
    # El mismo patrón que aplica el sed de los scripts.
    assert re.findall(r'^__version__ = "(.*)"', fuente, re.MULTILINE) == [__version__]

    sed_de_los_scripts = 'sed -n \'s/^__version__ = "\\(.*\\)"/\\1/p\' app/version.py'
    assert sed_de_los_scripts in (RAIZ / script).read_text(encoding="utf-8")


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_have_unix_line_endings(script):
    """Con CRLF fallan al ejecutarse en el servidor.

    El error no dice nada útil: /usr/bin/env: 'sh<CR>': No such file or
    directory. Se fija en .gitattributes, y esto lo comprueba.
    """
    assert b"\r" not in (RAIZ / script).read_bytes()


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_start_with_a_shebang(script):
    primera = (RAIZ / script).read_text(encoding="utf-8").splitlines()[0]
    assert primera == "#!/usr/bin/env sh"


def test_gitattributes_pins_shell_scripts_to_lf():
    contenido = (RAIZ / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in contenido


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_are_valid_posix_shell(script):
    """`sh -n` analiza sin ejecutar: detecta un if o un heredoc sin cerrar."""
    sh = "/bin/sh" if Path("/bin/sh").exists() else None
    if sh is None:
        pytest.skip("no hay /bin/sh en este equipo")
    resultado = subprocess.run([sh, "-n", str(RAIZ / script)],
                               capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr


def test_the_default_port_is_the_same_everywhere():
    """El puerto por defecto está declarado en cuatro sitios y deben coincidir.

    Si divergieran, docker-up.sh esperaría el arranque en un puerto y la
    aplicación escucharía en otro: el script daría la instalación por fallida
    aunque el panel estuviese funcionando.
    """
    from app.config import Settings

    esperado = Settings.model_fields["port"].default

    ejemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert f"SM_PORT={esperado}" in ejemplo

    script = (RAIZ / "docker-up.sh").read_text(encoding="utf-8")
    assert f"PUERTO_DEFECTO={esperado}" in script

    actualizar = (RAIZ / "docker-update.sh").read_text(encoding="utf-8")
    assert f'[ -n "$PORT" ] || PORT={esperado}' in actualizar

    dockerfile = (RAIZ / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert f"SM_PORT={esperado}" in dockerfile
    assert f"EXPOSE {esperado}" in dockerfile


def test_compose_tags_the_image_with_the_version():
    """Sin etiqueta de versión, la vuelta atrás de docker-update.sh no tiene a dónde ir."""
    compose = (RAIZ / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "image: systemmonitor:${SM_VERSION:-latest}" in compose


def test_the_readme_badge_shows_the_current_version():
    """La insignia es texto fijo: sin este test se queda atrás en silencio."""
    from app.version import __version__

    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    encontrada = re.search(r"badge/versi%C3%B3n-([\d.]+)-", readme)
    assert encontrada, "no hay insignia de versión en el README"
    assert encontrada.group(1) == __version__


def test_the_readme_badges_match_the_project():
    """Las insignias son de este proyecto, no copiadas de otro."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    licencia = (RAIZ / "LICENSE").read_text(encoding="utf-8")

    # La licencia declarada tiene que ser la del fichero LICENSE.
    assert "licencia-MIT-" in readme
    assert "MIT License" in licencia

    # Y las versiones de Python, las que CI ejercita de verdad.
    ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for version in re.findall(r"badge/python-([\d.%\w]+)-", readme)[0].split("%20%7C%20"):
        assert f'"{version}"' in ci, f"el README anuncia Python {version} y CI no lo prueba"


def test_changelog_starts_with_the_current_version():
    """docker-update.sh muestra la primera sección al actualizar."""
    from app.version import __version__

    changelog = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    primera = re.search(r"^## \[(.+?)\]", changelog, re.MULTILINE)
    assert primera and primera.group(1) == __version__


def test_hashpw_stdin_prints_only_a_usable_hash():
    """docker-up.sh captura esta salida tal cual: cualquier texto extra la rompe."""
    from argon2 import PasswordHasher

    resultado = subprocess.run(
        [sys.executable, "-m", "app.tools.hashpw", "--stdin"],
        input="contrasena-de-prueba\n", capture_output=True, text=True, cwd=RAIZ,
    )
    assert resultado.returncode == 0, resultado.stderr
    salida = resultado.stdout.strip()
    assert salida.startswith("$argon2")
    assert "\n" not in salida, "debe imprimir solo el hash, sin texto alrededor"
    # Y el hash tiene que servir de verdad para verificar la contraseña.
    assert PasswordHasher().verify(salida, "contrasena-de-prueba")


def test_hashpw_rejects_an_empty_password():
    resultado = subprocess.run(
        [sys.executable, "-m", "app.tools.hashpw", "--stdin"],
        input="\n", capture_output=True, text=True, cwd=RAIZ,
    )
    assert resultado.returncode == 1
    assert not resultado.stdout.strip()


def test_credentials_are_detected_as_configured():
    from app.core.security import credentials_configured

    # conftest.py define SM_PASSWORD, así que aquí deben verse configuradas.
    assert credentials_configured() is True
