"""Conexion unica a SQLite.

Solo el bucle de persistencia escribe muestras, asi que una conexion basta y
evita el coste de abrir/cerrar. WAL permite que las lecturas del historico no
se bloqueen contra esas escrituras.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from ..config import settings

log = logging.getLogger(__name__)
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("La base de datos no esta inicializada")
        return self._conn

    async def connect(self) -> None:
        path = settings.db_file
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL en vez de FULL: en una Pi con tarjeta SD, un fsync por escritura
        # es caro y aqui perder el ultimo minuto de historico no es grave.
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        # Necesario para que la purga devuelva espacio al sistema de ficheros.
        await self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        await self._conn.commit()
        log.info("SQLite listo en %s", path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        cursor = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        async with self.conn.execute(sql, tuple(params)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        async with self.conn.execute(sql, tuple(params)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def audit(self, username: str, ip: str, action: str,
                    detail: str, ok: bool = True) -> None:
        await self.execute(
            "INSERT INTO audit_log (ts, username, ip, action, detail, ok)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (int(time.time()), username, ip, action, detail, int(ok)),
        )

    async def healthy(self) -> bool:
        try:
            await self.fetch_one("SELECT 1 AS ok")
            return True
        except Exception:
            log.exception("comprobacion de salud de SQLite fallida")
            return False


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


db = Database()
