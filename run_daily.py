#!/usr/bin/env python3
"""Orquestador diario: ingesta Gmail → auto-categoriza → envía reporte por email.

Por defecto reporta el día actual (hoy). Para uso en Task Scheduler a las 06:55
que reporta el día anterior, usar --yesterday.

Uso manual:
    python run_daily.py              # reporte de hoy
    python run_daily.py --yesterday  # reporte de ayer (cron matutino)

Para instalar la tarea programada:
    powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# ── Logging a archivo + consola (debe inicializarse antes de importar módulos) ─
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(
            _LOG_DIR / f"daily_{date.today().isoformat()}.log", encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)

import config  # noqa: E402
from categorizer import auto_categorize  # noqa: E402
from daily_report import send_daily_report  # noqa: E402
from db import Database  # noqa: E402
from gmail_ingest import GmailIngestor  # noqa: E402
from reconciler import Reconciler  # noqa: E402

LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Orquestador diario EconomicScript")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--yesterday",
        action="store_true",
        help="Reporta el día anterior (ejecución matutina programada).",
    )
    mode.add_argument(
        "--today",
        action="store_true",
        help="Reporta el día actual en modo parcial (ejecución vespertina). Es el default.",
    )
    p.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help=(
            "Revisa correos bancarios de los últimos N días (leídos y no leídos). "
            "Por defecto usa GMAIL_LOOKBACK_DAYS del .env (3). "
            "Poner 0 para solo UNSEEN."
        ),
    )
    return p.parse_args()


def _log_saved_by_day(conn: sqlite3.Connection, since_iso: str) -> None:
    """Registra en log cuántas transacciones nuevas hay por día de movimiento."""
    rows = conn.execute(
        """
        SELECT DATE(date) AS day, COUNT(*) AS n,
               SUM(CASE WHEN type LIKE 'Compra%' THEN 1 ELSE 0 END) AS compras,
               SUM(CASE WHEN type LIKE 'Transferencia%' THEN 1 ELSE 0 END) AS transferencias
        FROM transactions
        WHERE created_at >= ?
        GROUP BY day
        ORDER BY day
        """,
        (since_iso,),
    ).fetchall()
    if not rows:
        LOGGER.info("Transacciones nuevas guardadas por día: (ninguna en esta corrida)")
        return
    LOGGER.info("Transacciones nuevas guardadas por día de movimiento:")
    for r in rows:
        LOGGER.info(
            "  %s → %s total (%s compras, %s transferencias)",
            r["day"],
            r["n"],
            r["compras"],
            r["transferencias"],
        )


def run() -> None:
    args = _parse_args()
    today = date.today()
    # --yesterday = reporte completo del día anterior; default/--today = parcial de hoy
    report_yesterday = bool(args.yesterday)
    report_date = today - timedelta(days=1) if report_yesterday else today
    LOGGER.info("═══ Inicio ejecución — reporte del %s ═══", report_date.isoformat())

    # Inicializar BD (idempotente)
    db = Database(config.DB_PATH)
    db.init_schema(config.SCHEMA_PATH)

    lookback = (
        args.lookback_days
        if args.lookback_days is not None
        else getattr(config, "GMAIL_LOOKBACK_DAYS", 3)
    )

    # 1. Ingesta Gmail
    # lookback>0: SINCE (últimos N días, leídos y no leídos) — recupera correos
    # ya marcados leídos por el móvil/Gmail. Dedup por gmail_message_id.
    # lookback=0: solo UNSEEN (comportamiento histórico).
    if lookback > 0:
        since = today - timedelta(days=lookback)
        LOGGER.info(
            "Paso 1/3 — Ingesta Gmail (últimos %d días desde %s, leídos y no leídos)",
            lookback,
            since.isoformat(),
        )
        ingestor = GmailIngestor(db)
        summary = ingestor.ingest(since_date=since)
    else:
        LOGGER.info("Paso 1/3 — Ingesta Gmail (solo correos no leídos / UNSEEN)")
        ingestor = GmailIngestor(db)
        summary = ingestor.ingest()

    LOGGER.info(
        "Ingesta completada → encontrados: %(found)s | procesados: %(processed)s | "
        "omitidos: %(skipped)s | guardados: %(saved)s | fallidos: %(failed)s | "
        "duplicados: %(duplicates)s",
        summary,
    )

    run_started = date.today().isoformat()  # fallback; refined below
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # Marca temporal aproximada: últimas inserciones de hoy
        _log_saved_by_day(conn, f"{run_started} 00:00:00")

        # 2. Auto-categorización de transacciones nuevas
        LOGGER.info("Paso 2/3 — Auto-categorización")
        n = auto_categorize(conn)
        conn.commit()
        LOGGER.info("Transacciones auto-categorizadas: %d", n)
    finally:
        conn.close()

    # 2.5 Reconciliación gmail vs cartola (idempotente)
    LOGGER.info("Paso 2.5/3 — Reconciliación gmail vs cartola")
    rec_summary = Reconciler(db).reconcile()
    LOGGER.info("Reconciliación: %s", rec_summary)

    # 3. Envío del reporte diario
    LOGGER.info("Paso 3/3 — Envío del reporte por email")
    send_daily_report(report_date=report_date, partial=not report_yesterday)

    LOGGER.info("═══ Ejecución diaria completada ═══")


if __name__ == "__main__":
    run()
