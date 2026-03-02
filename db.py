"""Acceso y operaciones SQLite para el sistema financiero personal."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from models import TransactionRecord


class Database:
    """Cliente liviano para operaciones de persistencia."""

    def __init__(self, db_path: str = "finance.db") -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        """Crea conexión SQLite con row_factory tipo diccionario."""

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self, schema_path: str = "sql/schema.sql") -> None:
        """Inicializa esquema desde archivo SQL."""

        script = Path(schema_path).read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(script)

    def insert_transactions(self, transactions: Iterable[TransactionRecord]) -> int:
        """Inserta transacciones y retorna cantidad de filas escritas."""

        rows = [
            (
                t.bank,
                t.date.isoformat(),
                t.amount,
                t.type,
                t.merchant,
                t.source,
                t.raw_text,
                t.gmail_message_id,
                t.statement_ref,
            )
            for t in transactions
        ]
        if not rows:
            return 0

        with self.connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO transactions
                (bank, date, amount, type, merchant, source, raw_text, gmail_message_id, statement_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return conn.total_changes

    def save_unprocessed_email(
        self,
        gmail_message_id: str,
        sender: str,
        subject: str,
        raw_text: str,
        error_reason: str,
    ) -> None:
        """Guarda correo no procesado para revisión manual."""

        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO unprocessed_emails
                (gmail_message_id, sender, subject, raw_text, error_reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (gmail_message_id, sender, subject, raw_text, error_reason),
            )
