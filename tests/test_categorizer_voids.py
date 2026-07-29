"""Anulaciones no caen en Transporte por keyword UBER; van a Ajustes/Anulaciones."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from categorizer import auto_categorize, ensure_default_categories  # noqa: E402


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            keywords TEXT
        );
        CREATE TABLE category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT UNIQUE,
            category_id INTEGER
        );
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank TEXT,
            date TEXT,
            amount INTEGER,
            type TEXT,
            merchant TEXT,
            category_id INTEGER,
            source TEXT DEFAULT 'gmail',
            verified INTEGER DEFAULT 0,
            raw_text TEXT,
            gmail_message_id TEXT,
            statement_ref TEXT,
            content_hash TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )


def test_anulacion_uber_goes_to_ajustes_not_transporte() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _schema(conn)
    ensure_default_categories(conn)
    conn.execute(
        """
        INSERT INTO transactions(bank, date, amount, type, merchant, source)
        VALUES ('BCI', '2026-07-29', -9205, 'Anulación TC', 'PAYU *UBER TRIP SANTIAGO CL', 'gmail')
        """
    )
    conn.execute(
        """
        INSERT INTO transactions(bank, date, amount, type, merchant, source)
        VALUES ('BCI', '2026-07-29', 9455, 'Compra TC', 'PAYU *UBER TRIP SANTIAGO CL', 'gmail')
        """
    )
    n = auto_categorize(conn)
    assert n >= 2
    rows = {
        r["type"]: r["cat"]
        for r in conn.execute(
            """
            SELECT t.type, c.name AS cat
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            """
        )
    }
    assert rows["Anulación TC"] == "Ajustes/Anulaciones"
    assert rows["Compra TC"] == "Transporte"
    conn.close()
