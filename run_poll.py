#!/usr/bin/env python3
"""Polling automático: revisa Gmail cada pocos minutos y alerta al instante.

Diseñado para ejecutarse via Windows Task Scheduler cada 10 minutos.
Procesa solo correos UNSEEN (no leídos) y envía email inmediato por cada
transacción nueva detectada.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(
            _LOG_DIR / f"poll_{date.today().isoformat()}.log", encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)

import config  # noqa: E402
from categorizer import auto_categorize  # noqa: E402
from db import Database  # noqa: E402
from gmail_ingest import GmailIngestor  # noqa: E402
from instant_alert import send_instant_alert  # noqa: E402

LOGGER = logging.getLogger(__name__)
_LOCK_FILE = _LOG_DIR / "poll.lock"
_BACKLOG_THRESHOLD = 15  # correos encontrados: modo silencioso (sin alertas masivas)


def _get_max_transaction_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM transactions").fetchone()
    return int(row[0])


def _get_new_transaction_ids(conn: sqlite3.Connection, since_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM transactions WHERE id > ? ORDER BY id",
        (since_id,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _filter_today_ids(conn: sqlite3.Connection, ids: list[int]) -> list[int]:
    """Solo alerta transacciones de hoy — evita spam al procesar backlog histórico."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    today = date.today().isoformat()
    rows = conn.execute(
        f"""
        SELECT id FROM transactions
        WHERE id IN ({placeholders}) AND DATE(date) = ?
        ORDER BY id
        """,
        [*ids, today],
    ).fetchall()
    return [int(r[0]) for r in rows]


class _PollLock:
    """Evita ejecuciones concurrentes del poll (Task Scheduler + manual)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd = None

    def __enter__(self):
        import os
        import time

        for _ in range(3):
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                time.sleep(2)
        raise RuntimeError("Otro poll está en ejecución — omitiendo")

    def __exit__(self, exc_type, exc, tb):
        import os

        if self._fd is not None:
            os.close(self._fd)
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def run() -> None:
    try:
        with _PollLock(_LOCK_FILE):
            _run_locked()
    except RuntimeError as exc:
        LOGGER.warning("%s", exc)


def _run_locked() -> None:
    LOGGER.info("─── Poll Gmail iniciado ───")

    db = Database(config.DB_PATH)
    db.init_schema(config.SCHEMA_PATH)

    conn = sqlite3.connect(config.DB_PATH)
    try:
        max_id_before = _get_max_transaction_id(conn)
    finally:
        conn.close()

    ingestor = GmailIngestor(db)
    summary = ingestor.ingest()

    if summary["found"] == 0:
        LOGGER.info("Sin correos nuevos — poll finalizado")
        return

    LOGGER.info(
        "Ingesta → encontrados: %(found)s | procesados: %(processed)s | "
        "guardados: %(saved)s | fallidos: %(failed)s | omitidos: %(skipped)s",
        summary,
    )

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        n = auto_categorize(conn)
        conn.commit()
        LOGGER.info("Auto-categorizadas: %d", n)

        new_ids = _get_new_transaction_ids(conn, max_id_before)
        if not new_ids:
            alert_ids: list[int] = []
        elif summary["found"] > _BACKLOG_THRESHOLD:
            alert_ids = []
            LOGGER.info(
                "Backlog detectado (%d correos) — transacciones guardadas sin alerta masiva",
                summary["found"],
            )
        else:
            alert_ids = _filter_today_ids(conn, new_ids)
    finally:
        conn.close()

    if not new_ids:
        LOGGER.info("Correos procesados pero sin transacciones nuevas en BD")
    elif alert_ids:
        LOGGER.info("Enviando alerta instantánea (%d transacciones de hoy)", len(alert_ids))
        send_instant_alert(alert_ids)
    elif summary["found"] <= _BACKLOG_THRESHOLD:
        LOGGER.info(
            "Transacciones nuevas (%d) pero ninguna es de hoy — sin alerta",
            len(new_ids),
        )

    LOGGER.info("─── Poll finalizado ───")


if __name__ == "__main__":
    run()