"""Tests de gasto real, dedupe de fuentes y aprendizaje de categorías."""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import pytest

from categorizer import (
    assign_category_and_learn,
    auto_categorize,
    ensure_default_categories,
    reassign_merchant_category,
)
from report_utils import (
    build_uncategorized_html,
    fetch_transactions_grouped,
    fetch_uncategorized_expenses,
)
from utils import NON_CONSUMPTION_TYPES, is_real_expense


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            keywords TEXT DEFAULT '[]'
        );
        CREATE TABLE category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT,
            category_id INTEGER,
            UNIQUE(pattern, category_id)
        );
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            bank TEXT,
            date TEXT,
            amount INTEGER,
            type TEXT,
            merchant TEXT,
            category_id INTEGER,
            source TEXT,
            verified INTEGER DEFAULT 0
        );
        INSERT INTO transactions VALUES
         (1,'BCI','2026-07-19 10:00:00',10000,'Compra TC','JUMBO',NULL,'gmail',0),
         (2,'BCI','2026-07-19 10:00:00',10000,'Compra TC','JUMBO',NULL,'cartola',1),
         (3,'BCI','2026-07-19 11:00:00',50000,'Transferencia','X',NULL,'gmail',0),
         (4,'BCI','2026-07-19 12:00:00',200000,'Pago TC','Pago',NULL,'gmail',0),
         (5,'BCI','2026-07-18 09:00:00',3000,'Compra TC','LIDER',NULL,'cartola',0),
         (6,'BCI','2026-07-19 13:00:00',-5000,'Abono','DEV',NULL,'gmail',0);
        """
    )
    ensure_default_categories(c)
    return c


def test_is_real_expense_filters_types() -> None:
    assert is_real_expense(1000, "Compra TC") is True
    assert is_real_expense(1000, None) is True
    assert is_real_expense(0, "Compra TC") is False
    assert is_real_expense(-100, "Compra TC") is False
    for t in NON_CONSUMPTION_TYPES:
        assert is_real_expense(1000, t) is False


def test_grouped_excludes_transfers_and_dedupes_gmail_cartola(conn: sqlite3.Connection) -> None:
    groups = fetch_transactions_grouped(
        conn, since=date(2026, 7, 18), until=date(2026, 7, 19)
    )
    total = sum(g.total for g in groups)
    n = sum(len(g.transactions) for g in groups)
    # JUMBO gmail 10k + LIDER cartola no verificada 3k (cartola verified=1 excluida)
    assert total == 13_000
    assert n == 2


def test_grouped_can_include_all_when_flags_off(conn: sqlite3.Connection) -> None:
    groups = fetch_transactions_grouped(
        conn,
        since=date(2026, 7, 18),
        until=date(2026, 7, 19),
        consumption_only=False,
        dedupe_sources=False,
        expenses_only=True,
    )
    total = sum(g.total for g in groups)
    # 10k+10k+50k+200k+3k = 273k (sin abono negativo)
    assert total == 273_000


def test_uncategorized_only_real_consumption(conn: sqlite3.Connection) -> None:
    rows = fetch_uncategorized_expenses(
        conn, since=date(2026, 7, 19), until=date(2026, 7, 19)
    )
    assert len(rows) == 1
    assert rows[0]["merchant"] == "JUMBO"
    assert rows[0]["amount"] == 10_000


def test_uncategorized_html_link_and_empty() -> None:
    empty = build_uncategorized_html([], title="Pendientes")
    assert "categoriz" in empty.lower()

    class _R(dict):
        def __getitem__(self, k):  # type: ignore[no-untyped-def]
            return super().__getitem__(k)

    # sqlite3.Row-like via simple namespace
    class Fake:
        def __init__(self, d):
            self._d = d

        def __getitem__(self, k):
            return self._d[k]

    rows = [
        Fake(
            {
                "date": "2026-07-19 10:00:00",
                "bank": "BCI",
                "merchant": "JUMBO",
                "type": "Compra TC",
                "amount": 1000,
            }
        )
    ]
    html = build_uncategorized_html(
        rows, title="Pendientes", dashboard_url="http://localhost:8501"
    )
    assert "view=categorizar" in html
    assert "JUMBO" in html


def test_reassign_merchant_learns_and_applies(conn: sqlite3.Connection) -> None:
    cat = conn.execute(
        "SELECT id FROM categories WHERE name = 'Alimentación'"
    ).fetchone()
    assert cat is not None
    n = reassign_merchant_category(conn, "jumbo", int(cat["id"]))
    # gmail + cartola jumbo (normalized match) = 2
    assert n == 2
    rule = conn.execute(
        "SELECT category_id FROM category_rules WHERE UPPER(pattern)='JUMBO'"
    ).fetchone()
    assert rule is not None
    assert int(rule["category_id"]) == int(cat["id"])


def test_assign_replaces_previous_rule(conn: sqlite3.Connection) -> None:
    alim = conn.execute(
        "SELECT id FROM categories WHERE name = 'Alimentación'"
    ).fetchone()
    otros = conn.execute(
        "SELECT id FROM categories WHERE name = 'Otros'"
    ).fetchone()
    assert alim and otros
    assign_category_and_learn(conn, 1, int(alim["id"]), "JUMBO")
    assign_category_and_learn(conn, 1, int(otros["id"]), "JUMBO")
    rules = conn.execute(
        "SELECT category_id FROM category_rules WHERE UPPER(pattern)='JUMBO'"
    ).fetchall()
    assert len(rules) == 1
    assert int(rules[0]["category_id"]) == int(otros["id"])


def test_auto_categorize_uses_learned_rule(conn: sqlite3.Connection) -> None:
    alim = conn.execute(
        "SELECT id FROM categories WHERE name = 'Alimentación'"
    ).fetchone()
    assert alim
    # Aprende por LIDER; deja JUMBO sin categoría
    assign_category_and_learn(conn, 5, int(alim["id"]), "LIDER")
    # Reset category on LIDER-like pattern already set — insert new uncategorized LIDER
    conn.execute(
        "INSERT INTO transactions VALUES (7,'BCI','2026-07-20 09:00:00',1500,'Compra TC','LIDER EXPRESS',NULL,'gmail',0)"
    )
    n = auto_categorize(conn)
    assert n >= 1
    row = conn.execute("SELECT category_id FROM transactions WHERE id=7").fetchone()
    assert row["category_id"] is not None


def test_filter_real_expenses_dataframe() -> None:
    """Replica la lógica de app._filter_real_expenses sin importar streamlit."""
    from utils import NON_CONSUMPTION_TYPES

    df = pd.DataFrame(
        {
            "amount": [100, 200, 300, -50, 400],
            "type": ["Compra TC", "Transferencia", "Pago TC", "Compra TC", None],
            "source": ["gmail", "gmail", "gmail", "gmail", "cartola"],
            "verified": [0, 0, 0, 0, 1],
        }
    )
    mask_amount = df["amount"] > 0
    mask_type = df["type"].isna() | ~df["type"].isin(NON_CONSUMPTION_TYPES)
    mask_source = (df["source"] == "gmail") | (
        (df["source"] == "cartola") & (df["verified"].fillna(0) == 0)
    )
    out = df[mask_amount & mask_type & mask_source]
    # solo fila 0 (compra gmail); fila 4 cartola verified=1 excluida; type None amount 400 would pass type but cartola verified
    assert list(out.index) == [0]
    assert int(out.iloc[0]["amount"]) == 100
