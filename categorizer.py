"""Categorización automática y aprendizaje de reglas."""

from __future__ import annotations

import sqlite3


def auto_categorize(conn: sqlite3.Connection) -> int:
    """Aplica reglas pattern->categoría sobre transacciones sin categoría."""

    rules = conn.execute("SELECT pattern, category_id FROM category_rules").fetchall()
    updated = 0
    for rule in rules:
        cursor = conn.execute(
            """
            UPDATE transactions
            SET category_id=?
            WHERE category_id IS NULL
            AND UPPER(merchant) LIKE UPPER(?)
            """,
            (rule["category_id"], f"%{rule['pattern']}%"),
        )
        updated += cursor.rowcount
    return updated


def assign_category_and_learn(
    conn: sqlite3.Connection,
    transaction_id: int,
    category_id: int,
    merchant: str,
) -> None:
    """Asigna categoría manualmente y crea regla de aprendizaje automático."""

    conn.execute("UPDATE transactions SET category_id=? WHERE id=?", (category_id, transaction_id))
    conn.execute(
        "INSERT INTO category_rules(pattern, category_id) VALUES(?, ?)",
        (merchant.split()[0].upper(), category_id),
    )
