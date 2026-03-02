"""Módulo de reconciliación entre fuentes Gmail y cartolas."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from db import Database

LOGGER = logging.getLogger(__name__)


class Reconciler:
    """Cruza transacciones por banco, fecha con tolerancia y monto exacto."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def reconcile(self) -> dict[str, int]:
        """Ejecuta reconciliación y retorna resumen por estado."""

        with self.db.connect() as conn:
            gmail_rows = conn.execute(
                "SELECT * FROM transactions WHERE source='gmail'"
            ).fetchall()
            cartola_rows = conn.execute(
                "SELECT * FROM transactions WHERE source='cartola'"
            ).fetchall()

            matched_cartola_ids: set[int] = set()
            summary = {"verified": 0, "gmail_only": 0, "cartola_only": 0}

            for gmail_tx in gmail_rows:
                match = self._find_match(gmail_tx, cartola_rows, matched_cartola_ids)
                if match:
                    matched_cartola_ids.add(match["id"])
                    summary["verified"] += 1
                    conn.execute("UPDATE transactions SET verified=1 WHERE id IN (?, ?)", (gmail_tx["id"], match["id"]))
                    conn.execute(
                        "INSERT INTO reconciliation_log(transaction_id, match_status, matched_with_id) VALUES (?, 'verified', ?)",
                        (gmail_tx["id"], match["id"]),
                    )
                else:
                    summary["gmail_only"] += 1
                    conn.execute(
                        "INSERT INTO reconciliation_log(transaction_id, match_status, matched_with_id) VALUES (?, 'gmail_only', NULL)",
                        (gmail_tx["id"],),
                    )

            for cartola_tx in cartola_rows:
                if cartola_tx["id"] not in matched_cartola_ids:
                    summary["cartola_only"] += 1
                    conn.execute(
                        "INSERT INTO reconciliation_log(transaction_id, match_status, matched_with_id) VALUES (?, 'cartola_only', NULL)",
                        (cartola_tx["id"],),
                    )

        LOGGER.info("Resultado reconciliación: %s", summary)
        return summary

    @staticmethod
    def _find_match(gmail_tx, cartola_rows, matched_cartola_ids: set[int]):
        g_date = datetime.fromisoformat(gmail_tx["date"])
        for row in cartola_rows:
            if row["id"] in matched_cartola_ids:
                continue
            if row["bank"] != gmail_tx["bank"] or row["amount"] != gmail_tx["amount"]:
                continue
            c_date = datetime.fromisoformat(row["date"])
            if abs((g_date.date() - c_date.date()).days) <= 1:
                return row
        return None
