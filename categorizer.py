"""Categorización automática y aprendizaje de reglas."""

from __future__ import annotations

import re
import sqlite3


def _escape_like(pattern: str) -> str:
    """Escapa caracteres especiales de SQLite LIKE (%, _, \\)."""
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_merchant(merchant: str) -> str:
    """Normaliza nombre de comercio: mayúsculas, sin espacios redundantes."""
    return re.sub(r"\s+", " ", merchant.strip()).upper()


def auto_categorize(conn: sqlite3.Connection) -> int:
    """Aplica reglas pattern->categoría sobre transacciones sin categoría."""

    rules = conn.execute("SELECT pattern, category_id FROM category_rules").fetchall()
    updated = 0
    for rule in rules:
        escaped = _escape_like(rule["pattern"])
        cursor = conn.execute(
            """
            UPDATE transactions
            SET category_id=?
            WHERE category_id IS NULL
            AND UPPER(merchant) LIKE UPPER(?) ESCAPE '\\'
            """,
            (rule["category_id"], f"%{escaped}%"),
        )
        updated += cursor.rowcount
    return updated


def assign_category_and_learn(
    conn: sqlite3.Connection,
    transaction_id: int,
    category_id: int,
    merchant: str,
) -> None:
    """Asigna categoría manualmente y aprende el comercio completo como regla."""

    conn.execute(
        "UPDATE transactions SET category_id=? WHERE id=?",
        (category_id, transaction_id),
    )
    # Usa el comercio completo normalizado como patrón (no solo la primera palabra)
    pattern = _normalize_merchant(merchant)
    conn.execute(
        "INSERT OR IGNORE INTO category_rules(pattern, category_id) VALUES(?, ?)",
        (pattern, category_id),
    )
