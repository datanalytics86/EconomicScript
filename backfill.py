"""Backfill histórico de correos Gmail desde una fecha (SINCE).

Seguro frente a duplicados: INSERT OR IGNORE por gmail_message_id y se omiten
UIDs ya presentes en la BD antes de fetch IMAP.

Uso:
    python backfill.py
    python backfill.py --since 2026-07-01
    python backfill.py --since 2026-07-01 --no-categorize

Por defecto rellena desde 2026-07-01 (hueco detectado en julio 2026).
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date, datetime

import config
from categorizer import auto_categorize
from db import Database
from gmail_ingest import GmailIngestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill Gmail EconomicScript")
    p.add_argument(
        "--since",
        type=str,
        default="2026-07-01",
        help="Fecha inicial ISO (YYYY-MM-DD). Default: 2026-07-01",
    )
    p.add_argument(
        "--no-categorize",
        action="store_true",
        help="No ejecutar auto-categorización al terminar.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    since = datetime.strptime(args.since, "%Y-%m-%d").date()

    db = Database(config.DB_PATH)
    db.init_schema(config.SCHEMA_PATH)
    ingestor = GmailIngestor(db)

    print(f"Iniciando backfill desde {since.isoformat()}…")
    print("(Dedup por gmail_message_id — no crea filas duplicadas en BD)")
    summary = ingestor.ingest(since_date=since)
    print("Backfill completado:")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if not args.no_categorize and summary.get("saved", 0) > 0:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            n = auto_categorize(conn)
            conn.commit()
            print(f"Auto-categorizadas: {n}")
        finally:
            conn.close()

    # Resumen por día de las TX insertadas hoy (aprox. esta corrida)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT DATE(date) AS day, COUNT(*) AS n
            FROM transactions
            WHERE DATE(created_at) = DATE('now')
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()
        if rows:
            print("Transacciones con created_at=hoy, por día de movimiento:")
            for day, n in rows:
                print(f"  {day}: {n}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
