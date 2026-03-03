#!/usr/bin/env python3
"""Orquestador diario: ingesta Gmail → auto-categoriza → envía reporte por email.

Diseñado para ejecutarse automáticamente via Windows Task Scheduler a las 06:55.
El reporte cubre las transacciones del día anterior (ayer) y el acumulado del ciclo.

Uso manual:
    python run_daily.py

Para instalar la tarea programada:
    powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
"""

from __future__ import annotations

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

LOGGER = logging.getLogger(__name__)


def run() -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)
    LOGGER.info("═══ Inicio ejecución diaria — reporte del %s ═══", yesterday.isoformat())

    # Inicializar BD (idempotente)
    db = Database(config.DB_PATH)
    db.init_schema(config.SCHEMA_PATH)

    # 1. Ingesta Gmail: correos del día anterior (ALL SINCE ayer)
    LOGGER.info("Paso 1/3 — Ingesta Gmail desde %s", yesterday.isoformat())
    ingestor = GmailIngestor(db)
    summary = ingestor.ingest(since_date=yesterday)
    LOGGER.info(
        "Ingesta completada → encontrados: %(found)s | procesados: %(processed)s | "
        "guardados: %(saved)s | fallidos: %(failed)s",
        summary,
    )

    # 2. Auto-categorización de transacciones nuevas
    LOGGER.info("Paso 2/3 — Auto-categorización")
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        n = auto_categorize(conn)
        conn.commit()
        LOGGER.info("Transacciones auto-categorizadas: %d", n)
    finally:
        conn.close()

    # 3. Envío del reporte diario
    LOGGER.info("Paso 3/3 — Envío del reporte por email")
    send_daily_report(report_date=yesterday)

    LOGGER.info("═══ Ejecución diaria completada ═══")


if __name__ == "__main__":
    run()
