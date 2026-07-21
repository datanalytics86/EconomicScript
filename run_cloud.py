#!/usr/bin/env python3
"""Ejecutor en la nube (GitHub Actions) — alertas sin PC encendido.

Horarios Chile (America/Santiago): 07:00, 14:00 y 21:00.
En cada horario: ingesta Gmail → categoriza → envía reporte por email.

Uso local (prueba):
    python run_cloud.py --force-slot morning
    python run_cloud.py --force-slot afternoon
    python run_cloud.py --force-slot evening
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

import config  # noqa: E402
from categorizer import auto_categorize  # noqa: E402
from daily_report import send_daily_report  # noqa: E402
from db import Database  # noqa: E402
from gmail_ingest import GmailIngestor  # noqa: E402
from reconciler import Reconciler  # noqa: E402

LOGGER = logging.getLogger(__name__)

SANTIAGO = ZoneInfo(config.TIMEZONE)
# Hora local Chile → slot de reporte
SCHEDULE: dict[int, str] = {7: "morning", 14: "afternoon", 21: "evening"}

SLOT_LABELS = {
    "morning": "07:00 — resumen de ayer",
    "afternoon": "14:00 — gastos de hoy",
    "evening": "21:00 — cierre del día",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EconomicScript — ejecución en la nube")
    p.add_argument(
        "--force-slot",
        choices=["morning", "afternoon", "evening"],
        help="Ejecutar aunque no sea el horario (pruebas / workflow_dispatch).",
    )
    p.add_argument(
        "--skip-hour-check",
        action="store_true",
        help="Omitir verificación de horario (usar con --force-slot).",
    )
    return p.parse_args()


def _resolve_slot(args: argparse.Namespace) -> str | None:
    if args.force_slot:
        return args.force_slot
    hour = datetime.now(SANTIAGO).hour
    return SCHEDULE.get(hour)


def _report_params(slot: str, today: date) -> tuple[date, bool]:
    """Retorna (fecha_reporte, es_parcial)."""
    if slot == "morning":
        return today - timedelta(days=1), False
    return today, True


def run(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = _parse_args()

    now = datetime.now(SANTIAGO)
    slot = _resolve_slot(args)

    if not slot:
        LOGGER.info(
            "Hora actual %s — no es horario de alerta (7/14/21). Nada que hacer.",
            now.strftime("%H:%M"),
        )
        return

    if args.force_slot and not args.skip_hour_check and not os.getenv("GITHUB_ACTIONS"):
        LOGGER.info("Modo prueba: slot forzado → %s", slot)

    today = now.date()
    report_date, partial = _report_params(slot, today)
    label = SLOT_LABELS[slot]

    missing = config.missing_runtime_config(need_smtp=True)
    if missing:
        LOGGER.error("Secrets incompletos: %s", ", ".join(missing))
        sys.exit(1)

    LOGGER.info("═══ Cloud run — %s — reporte %s ═══", label, report_date.isoformat())

    db = Database(config.DB_PATH)
    db.init_schema(config.SCHEMA_PATH)

    LOGGER.info("Paso 1/3 — Ingesta Gmail")
    summary = GmailIngestor(db).ingest()
    LOGGER.info("Ingesta: %s", summary)

    LOGGER.info("Paso 2/3 — Auto-categorización")
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        n = auto_categorize(conn)
        conn.commit()
        LOGGER.info("Auto-categorizadas: %d", n)
    finally:
        conn.close()

    LOGGER.info("Paso 2.5/3 — Reconciliación")
    LOGGER.info("Reconciliación: %s", Reconciler(db).reconcile())

    LOGGER.info("Paso 3/3 — Envío reporte (%s)", label)
    send_daily_report(
        report_date=report_date,
        partial=partial,
        slot_label=label,
    )

    LOGGER.info("═══ Cloud run completado ═══")


if __name__ == "__main__":
    run()