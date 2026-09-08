"""Purga del historico antiguo.

Sin esto la base crece sin limite y en una tarjeta SD eso acaba en disco lleno,
que es justo lo que se supone que este panel debe avisar.
"""
from __future__ import annotations

import logging
import time

from ..config import settings
from .db import db

log = logging.getLogger(__name__)

EVENT_RETENTION_MULTIPLIER = 4  # los eventos de alerta pesan poco: se guardan mas


async def purge() -> dict[str, int]:
    now = int(time.time())
    sample_cutoff = now - settings.retention_days * 86400
    event_cutoff = now - settings.retention_days * EVENT_RETENTION_MULTIPLIER * 86400

    samples = await db.conn.execute("DELETE FROM samples WHERE ts < ?", (sample_cutoff,))
    events = await db.conn.execute("DELETE FROM alert_events WHERE ts < ?", (event_cutoff,))
    audit = await db.conn.execute("DELETE FROM audit_log WHERE ts < ?", (event_cutoff,))
    await db.conn.commit()

    deleted = {
        "samples": samples.rowcount or 0,
        "alert_events": events.rowcount or 0,
        "audit_log": audit.rowcount or 0,
    }
    if any(deleted.values()):
        # Incremental en vez de VACUUM completo: este ultimo reescribe el fichero
        # entero y en una SD es lento y castiga la escritura.
        await db.conn.execute("PRAGMA incremental_vacuum(200)")
        await db.conn.commit()
        log.info("purga del historico: %s", deleted)
    return deleted


async def stats() -> dict[str, int | float | None]:
    row = await db.fetch_one(
        "SELECT COUNT(*) AS rows, MIN(ts) AS oldest, MAX(ts) AS newest FROM samples")
    size = settings.db_file.stat().st_size if settings.db_file.exists() else 0
    return {
        "rows": (row or {}).get("rows", 0),
        "oldest": (row or {}).get("oldest"),
        "newest": (row or {}).get("newest"),
        "db_bytes": size,
        "retention_days": settings.retention_days,
    }
