"""Backfill histórico de correos Gmail desde SINCE_DATE.

Uso:
    python backfill.py

Cambia SINCE_DATE si necesitas otro punto de inicio.
"""
from __future__ import annotations

import logging
from datetime import date

import config
from db import Database
from gmail_ingest import GmailIngestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)

SINCE_DATE = date(2026, 3, 1)


def main() -> None:
    db = Database(config.DB_PATH)
    db.init_schema(config.SCHEMA_PATH)
    ingestor = GmailIngestor(db)
    print(f"Iniciando backfill desde {SINCE_DATE}…")
    summary = ingestor.ingest(since_date=SINCE_DATE)
    print("Backfill completado:")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
