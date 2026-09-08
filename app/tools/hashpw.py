"""Genera un hash Argon2 para SM_PASSWORD_HASH.

    python -m app.tools.hashpw              # interactivo, con instrucciones
    python -m app.tools.hashpw --stdin      # lee la contrasena de stdin

El modo --stdin imprime SOLO el hash, sin texto alrededor, para que
docker-up.sh pueda capturarlo. Se ejecuta dentro de la imagen ya construida,
asi el hash sale con los mismos parametros de Argon2 que usa el login: si
divergieran, la contrasena se verificaria con un coste distinto al previsto.

Preferible a dejar SM_PASSWORD en claro dentro del .env o del compose.
"""
from __future__ import annotations

import getpass
import sys

from app.core.security import hash_password


def _from_stdin() -> int:
    # Sin strip() completo: una contrasena puede empezar o acabar con espacios
    # a proposito. Solo se quita el salto de linea que anade el shell al leer.
    password = sys.stdin.readline().rstrip("\n").rstrip("\r")
    if not password:
        print("contrasena vacia", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


def _interactive() -> int:
    password = getpass.getpass("Contrasena: ")
    if not password:
        print("vacia, abortando", file=sys.stderr)
        return 1
    if password != getpass.getpass("Repite la contrasena: "):
        print("no coinciden", file=sys.stderr)
        return 1
    # Las comillas simples no son decorativas: sin ellas, tanto Docker Compose
    # como python-dotenv expanden los $ del hash, y el login rechaza incluso la
    # contrasena correcta con "usuario o contrasena incorrectos".
    print("\nAnade esta linea a tu .env y borra SM_PASSWORD.")
    print("Las comillas simples son obligatorias: el hash contiene '$'.\n")
    print(f"SM_PASSWORD_HASH='{hash_password(password)}'")
    return 0


def main() -> int:
    return _from_stdin() if "--stdin" in sys.argv[1:] else _interactive()


if __name__ == "__main__":
    raise SystemExit(main())
