"""Genera un hash Argon2 para SM_PASSWORD_HASH.

    python -m app.tools.hashpw

Preferible a dejar SM_PASSWORD en claro dentro del .env o del compose.
"""
from __future__ import annotations

import getpass
import sys

from argon2 import PasswordHasher

hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


def main() -> int:
    password = getpass.getpass("Contrasena: ")
    if not password:
        print("vacia, abortando", file=sys.stderr)
        return 1
    if password != getpass.getpass("Repite la contrasena: "):
        print("no coinciden", file=sys.stderr)
        return 1
    digest = hasher.hash(password)
    print("\nAnade esta linea a tu .env (entre comillas simples en docker-compose,")
    print("porque el hash contiene el caracter $):\n")
    print(f"SM_PASSWORD_HASH={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
