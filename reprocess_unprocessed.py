"""Reintenta parsear correos ya guardados en unprocessed_emails.

Útil tras mejorar parsers: no toca IMAP; solo lee la BD local.
Las transacciones nuevas se insertan con INSERT OR IGNORE (sin duplicados).
Los registros re-parseados con éxito se eliminan de unprocessed_emails.

Uso:
    python reprocess_unprocessed.py
    python reprocess_unprocessed.py --limit 100
    python reprocess_unprocessed.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sqlite3

import config
from db import Database
from parsers import BCIParser, BancoEstadoParser, SecurityParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s")
LOGGER = logging.getLogger("reprocess")

PARSERS = [BCIParser(), BancoEstadoParser(), SecurityParser()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="Máximo de filas a intentar (0=todas)")
    p.add_argument("--dry-run", action="store_true", help="Solo reporta, no escribe BD")
    args = p.parse_args()

    db = Database(config.DB_PATH)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT id, gmail_message_id, sender, subject, raw_text, error_reason
        FROM unprocessed_emails
        WHERE raw_text IS NOT NULL AND LENGTH(raw_text) > 20
        ORDER BY id
    """
    if args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"

    rows = conn.execute(sql).fetchall()
    LOGGER.info("Candidatos a re-procesar: %d", len(rows))

    recovered = 0
    still_fail = 0
    no_parser = 0
    recovered_ids: list[int] = []

    for row in rows:
        sender = row["sender"] or ""
        subject = row["subject"] or ""
        body = row["raw_text"] or ""
        mid = row["gmail_message_id"]

        parser = next(
            (pr for pr in PARSERS if pr.can_parse(sender=sender, subject=subject, body=body)),
            None,
        )
        if not parser:
            no_parser += 1
            continue
        try:
            tx = parser.parse(body=body, gmail_message_id=mid)
        except Exception as exc:  # noqa: BLE001
            still_fail += 1
            LOGGER.debug("Sigue fallando id=%s: %s", row["id"], exc)
            continue

        if args.dry_run:
            LOGGER.info(
                "[dry-run] OK id=%s → %s %s $%s %s",
                row["id"],
                tx.date.date() if hasattr(tx.date, "date") else tx.date,
                tx.type,
                tx.amount,
                (tx.merchant or "")[:40],
            )
            recovered += 1
            recovered_ids.append(row["id"])
            continue

        if db.insert_transaction(tx):
            recovered += 1
            recovered_ids.append(row["id"])
            LOGGER.info(
                "Recuperada id=%s → %s | %s | $%s | %s",
                row["id"],
                tx.date.strftime("%Y-%m-%d") if hasattr(tx.date, "strftime") else tx.date,
                tx.type,
                f"{tx.amount:,}".replace(",", "."),
                (tx.merchant or "")[:50],
            )
        else:
            # Ya existía en transactions — limpiar unprocessed
            recovered_ids.append(row["id"])
            LOGGER.info("Duplicado ya en BD, limpiando unprocessed id=%s", row["id"])

    if recovered_ids and not args.dry_run:
        placeholders = ",".join("?" * len(recovered_ids))
        conn.execute(
            f"DELETE FROM unprocessed_emails WHERE id IN ({placeholders})",
            recovered_ids,
        )
        conn.commit()

    conn.close()
    print(
        f"Listo — recuperadas: {recovered} | sin parser: {no_parser} | "
        f"siguen fallando: {still_fail} | limpiadas: {len(recovered_ids)}"
    )


if __name__ == "__main__":
    main()
