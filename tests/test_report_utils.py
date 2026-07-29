"""Tests del motor de gasto de consumo neto y neteo por comercio."""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_utils import (  # noqa: E402
    fetch_transactions_grouped,
    net_lines_from_rows,
)
from utils import get_cycle_label, get_cycle_start_date  # noqa: E402


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
        INSERT INTO categories(id, name) VALUES
            (1, 'Transporte'), (2, 'Transferencias'), (3, 'Ajustes/Anulaciones');
        INSERT INTO transactions(id, bank, date, amount, type, merchant, category_id) VALUES
            (1, 'BCI', '2026-07-26 00:00:00', 8000, 'Compra TC', 'PAYU *UBER', 1),
            (2, 'BCI', '2026-07-26 00:00:00', 8190, 'Compra TC', 'PAYU *UBER', 1),
            (3, 'BCI', '2026-07-26 00:00:00', -8000, 'Anulación TC', 'PAYU *UBER', 3),
            (4, 'BCI', '2026-07-26 00:00:00', 100000, 'Transferencia', 'Nicolas', 2),
            (5, 'BCI', '2026-07-26 00:00:00', 50000, 'Pago TC', 'Pago TC ****', NULL),
            (6, 'BCI', '2026-07-26 00:00:00', 1000, 'Compra TC', 'CAFE X', 1),
            (7, 'BCI', '2026-07-26 00:00:00', -990, 'Anulación TC', 'CAFE X', 3);
        """
    )


def test_net_lines_uber_and_partial_void() -> None:
    """Uber 8000+8190-8000=8190; CAFE 1000-990=10; sin listar anulaciones."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    rows = conn.execute(
        """
        SELECT t.*, COALESCE(c.name,'Sin categoría') AS category
        FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.type NOT LIKE 'Transferencia%' AND t.type NOT LIKE 'Pago TC%'
        """
    ).fetchall()
    lines = net_lines_from_rows(rows)
    by_m = {L.merchant.upper(): L.amount for L in lines}
    assert by_m["PAYU *UBER"] == 8190
    assert by_m["CAFE X"] == 10
    assert sum(L.amount for L in lines) == 8200
    # No línea con amount negativo de void suelta
    assert all(L.amount > 0 for L in lines)


def test_fetch_grouped_nets_anulaciones() -> None:
    """Provisorio + final + anulación → neto día = 8200 (uber 8190 + cafe 10)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    groups = fetch_transactions_grouped(
        conn, since=date(2026, 7, 26), until=date(2026, 7, 26), expenses_only=True
    )
    grand = sum(g.total for g in groups)
    assert grand == 8200
    # Sin categoría Ajustes visible
    assert all(g.category != "Ajustes/Anulaciones" for g in groups)
    # Transferencias fuera
    types_in_lines = []
    for g in groups:
        for L in g.lines:
            types_in_lines.append(L.merchant)
    assert not any("Nicolas" in m for m in types_in_lines)


def test_fetch_grouped_all_includes_transfers() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    groups = fetch_transactions_grouped(
        conn,
        since=date(2026, 7, 26),
        until=date(2026, 7, 26),
        expenses_only=False,
        net_display=False,
    )
    types_seen = {r["type"] for g in groups for r in g.transactions}
    assert "Transferencia" in types_seen


def test_expenses_only_never_includes_transfers() -> None:
    """Transferencias y pagos TC no entran al total de gasto ni a categorías."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    groups = fetch_transactions_grouped(
        conn, since=date(2026, 7, 26), until=date(2026, 7, 26), expenses_only=True
    )
    assert all(g.category not in ("Transferencias", "Pagos tarjeta", "Ingresos") for g in groups)
    # Seed tiene transferencia 100000 y pago 50000; no deben inflar el total
    assert sum(g.total for g in groups) == 8200  # uber 8190 + cafe 10


def test_cycle_starts_on_27() -> None:
    assert get_cycle_start_date(date(2026, 7, 29)) == date(2026, 7, 27)
    assert get_cycle_start_date(date(2026, 8, 10)) == date(2026, 7, 27)
    assert get_cycle_start_date(date(2026, 8, 27)) == date(2026, 8, 27)
    assert get_cycle_start_date(date(2026, 7, 15)) == date(2026, 6, 27)


def test_cycle_label_agosto() -> None:
    # 27/jul–26/ago → Agosto
    assert get_cycle_label(date(2026, 7, 29)) == "Agosto"
    assert get_cycle_label(date(2026, 8, 10)) == "Agosto"
    # 27/ago en adelante → Septiembre
    assert get_cycle_label(date(2026, 8, 27)) == "Septiembre"
