"""Tests del motor de gasto de consumo neto en reportes."""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_utils import fetch_transactions_grouped  # noqa: E402


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT,
            keywords TEXT
        );
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
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
        INSERT INTO categories(id, name) VALUES (1, 'Transporte'), (2, 'Transferencias');
        INSERT INTO transactions(id, bank, date, amount, type, merchant, category_id) VALUES
            (1, 'BCI', '2026-07-26 00:00:00', 8000, 'Compra TC', 'PAYU *UBER', 1),
            (2, 'BCI', '2026-07-26 00:00:00', 8190, 'Compra TC', 'PAYU *UBER', 1),
            (3, 'BCI', '2026-07-26 00:00:00', -8000, 'Anulación TC', 'PAYU *UBER', 1),
            (4, 'BCI', '2026-07-26 00:00:00', 100000, 'Transferencia', 'Nicolas', 2),
            (5, 'BCI', '2026-07-26 00:00:00', 50000, 'Pago TC', 'Pago TC ****', NULL);
        """
    )


def test_fetch_grouped_nets_anulaciones() -> None:
    """Provisorio + final + anulación → neto día = 8190 (puede estar en 1 o 2 categorías)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    groups = fetch_transactions_grouped(
        conn, since=date(2026, 7, 26), until=date(2026, 7, 26), expenses_only=True
    )
    # Transferencias y pagos fuera del consumo
    types_seen = {r["type"] for g in groups for r in g.transactions}
    assert "Transferencia" not in types_seen
    assert "Pago TC" not in types_seen
    # Neto total del día = 8000 + 8190 - 8000
    grand = sum(g.total for g in groups)
    assert grand == 8190
    n_mov = sum(len(g.transactions) for g in groups)
    assert n_mov == 3


def test_fetch_grouped_all_includes_transfers() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    groups = fetch_transactions_grouped(
        conn, since=date(2026, 7, 26), until=date(2026, 7, 26), expenses_only=False
    )
    types_seen = {r["type"] for g in groups for r in g.transactions}
    assert "Transferencia" in types_seen
    grand_consumo = sum(
        r["amount"]
        for g in groups
        for r in g.transactions
        if r["type"] in ("Compra TC", "Anulación TC")
    )
    assert grand_consumo == 8190
