"""Módulo de reconciliación entre fuentes Gmail y cartolas."""

from __future__ import annotations

import logging
from datetime import datetime

import config
from db import Database

LOGGER = logging.getLogger(__name__)


class Reconciler:
    """Cruza transacciones por banco, fecha con tolerancia y monto exacto."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def reconcile(self) -> dict[str, int]:
        """Ejecuta reconciliación idempotente y retorna resumen por estado.

        Es seguro ejecutar múltiples veces: solo procesa transacciones
        que aún no tienen entrada en reconciliation_log.
        """

        with self.db.connect() as conn:
            # IDs ya presentes en el log (para idempotencia)
            already_logged: set[int] = {
                row[0] for row in conn.execute("SELECT transaction_id FROM reconciliation_log")
            }
            already_matched_cartola: set[int] = {
                row[0]
                for row in conn.execute(
                    "SELECT matched_with_id FROM reconciliation_log WHERE matched_with_id IS NOT NULL"
                )
            }

            gmail_rows = [
                r
                for r in conn.execute("SELECT * FROM transactions WHERE source='gmail'").fetchall()
                if r["id"] not in already_logged
            ]
            cartola_rows = conn.execute(
                "SELECT * FROM transactions WHERE source='cartola'"
            ).fetchall()

            matched_cartola_ids: set[int] = set(already_matched_cartola)
            summary = {"verified": 0, "gmail_only": 0, "cartola_only": 0}
            tolerance = config.RECONCILIATION_DATE_TOLERANCE_DAYS

            for gmail_tx in gmail_rows:
                match = self._find_match(gmail_tx, cartola_rows, matched_cartola_ids, tolerance)
                if match:
                    matched_cartola_ids.add(match["id"])
                    summary["verified"] += 1
                    conn.execute(
                        "UPDATE transactions SET verified=1 WHERE id IN (?, ?)",
                        (gmail_tx["id"], match["id"]),
                    )
                    conn.execute(
                        "INSERT INTO reconciliation_log"
                        "(transaction_id, match_status, matched_with_id) VALUES (?, 'verified', ?)",
                        (gmail_tx["id"], match["id"]),
                    )
                else:
                    summary["gmail_only"] += 1
                    conn.execute(
                        "INSERT INTO reconciliation_log"
                        "(transaction_id, match_status, matched_with_id) VALUES (?, 'gmail_only', NULL)",
                        (gmail_tx["id"],),
                    )

            for cartola_tx in cartola_rows:
                if (
                    cartola_tx["id"] not in matched_cartola_ids
                    and cartola_tx["id"] not in already_logged
                ):
                    summary["cartola_only"] += 1
                    conn.execute(
                        "INSERT INTO reconciliation_log"
                        "(transaction_id, match_status, matched_with_id) VALUES (?, 'cartola_only', NULL)",
                        (cartola_tx["id"],),
                    )

        LOGGER.info("Resultado reconciliación: %s", summary)
        return summary

    @staticmethod
    def _find_match(
        gmail_tx,
        cartola_rows: list,
        matched_cartola_ids: set[int],
        tolerance_days: int,
    ):
        try:
            g_date = datetime.fromisoformat(gmail_tx["date"])
        except (ValueError, TypeError) as exc:
            LOGGER.warning(
                "Fecha inválida en transacción gmail id=%s: %s", gmail_tx["id"], exc
            )
            return None

        for row in cartola_rows:
            if row["id"] in matched_cartola_ids:
                continue
            if row["bank"] != gmail_tx["bank"] or row["amount"] != gmail_tx["amount"]:
                continue
            try:
                c_date = datetime.fromisoformat(row["date"])
            except (ValueError, TypeError):
                continue
            if abs((g_date.date() - c_date.date()).days) <= tolerance_days:
                return row
        return None
