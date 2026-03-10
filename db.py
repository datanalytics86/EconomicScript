"""Acceso y operaciones SQLite para el sistema financiero personal."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from models import TransactionRecord

LOGGER = logging.getLogger(__name__)
_DB_TIMEOUT = 10  # segundos antes de lanzar OperationalError por bloqueo concurrente


class Database:
    """Cliente liviano para operaciones de persistencia."""

    def __init__(self, db_path: str = "finance.db") -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        """Crea conexión SQLite con row_factory tipo diccionario y FK activas."""

        conn = sqlite3.connect(self.db_path, timeout=_DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self, schema_path: str = "sql/schema.sql") -> None:
        """Inicializa esquema y aplica migraciones sin pérdida de datos."""

        schema_file = Path(schema_path)
        if not schema_file.exists():
            raise FileNotFoundError(f"Esquema SQL no encontrado: {schema_path}")
        script = schema_file.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(script)
        self._run_migrations()
        LOGGER.info("Esquema inicializado correctamente desde %s", schema_path)

    def _run_migrations(self) -> None:
        """Agrega columnas nuevas sin perder datos en bases existentes."""

        with self.connect() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
            if "content_hash" not in cols:
                conn.execute("ALTER TABLE transactions ADD COLUMN content_hash TEXT")
                LOGGER.info("Migración aplicada: columna content_hash agregada a transactions")

    def insert_transactions(self, transactions: Iterable[TransactionRecord]) -> int:
        """Inserta transacciones ignorando duplicados. Retorna filas efectivamente escritas."""

        rows = [
            (
                t.bank,
                t.date.strftime("%Y-%m-%d %H:%M:%S"),  # naive local (hora chilena, sin offset)
                t.amount,
                t.type,
                t.merchant,
                t.source,
                t.raw_text,
                t.gmail_message_id,
                t.statement_ref,
                t.content_hash,
            )
            for t in transactions
        ]
        if not rows:
            return 0

        with self.connect() as conn:
            cursor = conn.executemany(
                """
                INSERT OR IGNORE INTO transactions
                (bank, date, amount, type, merchant, source, raw_text,
                 gmail_message_id, statement_ref, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = cursor.rowcount
            LOGGER.debug("Insertadas %s/%s transacciones", inserted, len(rows))
            return inserted

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


# ── Funciones de soporte para el dashboard ─────────────────────────────────────

def get_transactions_for_export(
    conn: sqlite3.Connection,
    since=None,
    until=None,
    bank: str | None = None,
    uncategorized_only: bool = False,
) -> list[dict]:
    """Devuelve transacciones como lista de dicts para exportar a Excel."""
    filters: list[str] = []
    params: list = []
    if since:
        filters.append("DATE(t.date) >= ?")
        params.append(since.isoformat() if hasattr(since, "isoformat") else str(since))
    if until:
        filters.append("DATE(t.date) <= ?")
        params.append(until.isoformat() if hasattr(until, "isoformat") else str(until))
    if bank:
        filters.append("t.bank = ?")
        params.append(bank)
    if uncategorized_only:
        filters.append("t.category_id IS NULL")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    rows = conn.execute(
        f"""
        SELECT t.id, DATE(t.date) AS fecha, t.bank AS banco, t.amount AS monto,
               t.type AS tipo, t.merchant AS comercio,
               COALESCE(c.name, '') AS categoria_actual
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        {where}
        ORDER BY t.date DESC
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_or_create_category(conn: sqlite3.Connection, name: str) -> int:
    """Retorna id de categoría existente o la crea si no existe (case-insensitive)."""
    row = conn.execute(
        "SELECT id FROM categories WHERE UPPER(name) = UPPER(?)", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO categories(name, keywords) VALUES(?, ?)",
        (name, json.dumps([])),
    )
    return cursor.lastrowid
