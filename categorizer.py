"""Categorización automática y aprendizaje de reglas."""

from __future__ import annotations

import json
import re
import sqlite3

# Categorías por defecto y keywords para clasificar comercios chilenos comunes
_DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Alimentación": [
        "UNIMARC", "JUMBO", "LIDER", "TOTTUS", "SUPERMERCADO", "SANTA ISABEL",
        "MAYORISTA 10", "OK MARKET", "ACUENTA", "RAPPI", "PEDIDOSYA", "UBER EATS",
        "CORNER", "MINIMARKET", "ALMACEN",
    ],
    "Restaurantes": [
        "RESTAURANT", "MCDONALDS", "BURGER", "STARBUCKS", "DOMINOS", "PIZZA",
        "SUSHI", "CAFE", "BAR ", "PUB ", "DELIVERY",
    ],
    "Transporte": [
        "COPEC", "SHELL", "PETROBRAS", "TERPEL", "UBER", "CABIFY", "DIDI",
        "ESTACIONAMIENTO", "PARKING", "TAG ", "AUTOPISTA", "METRO", "BIP",
    ],
    "Compras online": [
        "FALABELLA", "RIPLEY", "PARIS", "MERCADOLIBRE", "MELI", "MERPAGO",
        "AMAZON", "ALIEXPRESS", "SHEIN", "TEMU", "DAFITI", "HITES",
    ],
    "Suscripciones": [
        "NETFLIX", "SPOTIFY", "GOOGLE", "APPLE", "MICROSOFT", "ADOBE",
        "DISNEY", "HBO", "YOUTUBE", "CHATGPT", "OPENAI", "GITHUB",
    ],
    "Salud": [
        "FARMACIA", "CRUZ VERDE", "SALCOBRAND", "AHUMADA", "DR SIMI",
        "CLINICA", "HOSPITAL", "ISAPRE", "FONASA", "DENTAL", "LABORATORIO",
    ],
    "Hogar y servicios": [
        "ENEL", "CGE", "CHILQUINTA", "AGUAS", "ESSBIO", "GASCO", "LIPIGAS",
        "VTR", "MOVISTAR", "ENTEL", "WOM", "CLARO", "GTD", "MUNICIPALIDAD",
    ],
    "Entretención": [
        "CINE", "TICKETEK", "STEAM", "PLAYSTATION", "XBOX", "NINTENDO",
        "SPOTIFY", "CULTURAL", "MUSEO", "TEATRO",
    ],
    "Transferencias": [],
    "Pagos tarjeta": [],
    "Compras extranjero": [],
    "Ingresos": [],
    "Otros": [],
}

# Mapeo tipo de transacción → categoría (cuando no hay match por comercio)
_TYPE_CATEGORY_MAP: dict[str, str] = {
    "Transferencia": "Transferencias",
    "Transferencia Propia": "Transferencias",
    "Transferencia Entrante": "Ingresos",
    "Transferencia Recibida": "Ingresos",
    "Pago TC": "Pagos tarjeta",
    "Pago Producto": "Pagos tarjeta",
    "Compra TC FX": "Compras extranjero",
}


def _escape_like(pattern: str) -> str:
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_merchant(merchant: str) -> str:
    return re.sub(r"\s+", " ", merchant.strip()).upper()


def _get_category_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM categories WHERE UPPER(name) = UPPER(?)", (name,)
    ).fetchone()
    return int(row["id"]) if row else None


def ensure_default_categories(conn: sqlite3.Connection) -> int:
    """Crea categorías y reglas por defecto si no existen. Retorna reglas nuevas."""
    created_rules = 0
    for name, keywords in _DEFAULT_CATEGORIES.items():
        row = conn.execute(
            "SELECT id FROM categories WHERE UPPER(name) = UPPER(?)", (name,)
        ).fetchone()
        if row:
            cat_id = row["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO categories(name, keywords) VALUES(?, ?)",
                (name, json.dumps(keywords)),
            )
            cat_id = cursor.lastrowid

        for kw in keywords:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO category_rules(pattern, category_id) VALUES(?, ?)",
                (kw, cat_id),
            )
            created_rules += cursor.rowcount

    return created_rules


def _categorize_by_type(conn: sqlite3.Connection) -> int:
    """Asigna categoría según el tipo de transacción (transferencias, pagos TC, etc.)."""
    updated = 0
    for tx_type, cat_name in _TYPE_CATEGORY_MAP.items():
        cat_id = _get_category_id(conn, cat_name)
        if not cat_id:
            continue
        cursor = conn.execute(
            """
            UPDATE transactions SET category_id=?
            WHERE category_id IS NULL AND type = ?
            """,
            (cat_id, tx_type),
        )
        updated += cursor.rowcount
    return updated


def auto_categorize(conn: sqlite3.Connection) -> int:
    """Aplica reglas por comercio y luego por tipo de transacción."""
    ensure_default_categories(conn)

    updated = 0
    rules = conn.execute("SELECT pattern, category_id FROM category_rules").fetchall()
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

    updated += _categorize_by_type(conn)
    return updated


def _upsert_merchant_rule(
    conn: sqlite3.Connection,
    merchant: str,
    category_id: int,
) -> str:
    """Registra (o reemplaza) la regla del comercio. Retorna el pattern normalizado."""
    pattern = _normalize_merchant(merchant)
    if not pattern:
        return pattern
    # Una sola categoría “correcta” por comercio: limpia reglas previas del mismo pattern
    conn.execute("DELETE FROM category_rules WHERE UPPER(pattern) = UPPER(?)", (pattern,))
    conn.execute(
        "INSERT INTO category_rules(pattern, category_id) VALUES(?, ?)",
        (pattern, category_id),
    )
    return pattern


def assign_category_and_learn(
    conn: sqlite3.Connection,
    transaction_id: int,
    category_id: int,
    merchant: str,
) -> None:
    """Asigna categoría a una transacción y aprende la regla del comercio."""
    conn.execute(
        "UPDATE transactions SET category_id=? WHERE id=?",
        (category_id, transaction_id),
    )
    _upsert_merchant_rule(conn, merchant, category_id)


def reassign_merchant_category(
    conn: sqlite3.Connection,
    merchant: str,
    category_id: int,
    *,
    only_uncategorized: bool = False,
) -> int:
    """Reasigna todas las transacciones del mismo comercio y actualiza la regla.

    El match usa el comercio normalizado (mayúsculas, espacios colapsados) para
    unificar variantes menores del mismo nombre.

    Returns:
        Número de filas actualizadas en ``transactions``.
    """
    pattern = _normalize_merchant(merchant)
    if not pattern:
        return 0

    rows = conn.execute(
        "SELECT id, merchant, category_id FROM transactions"
    ).fetchall()
    ids: list[int] = []
    for row in rows:
        if only_uncategorized and row["category_id"] is not None:
            continue
        if _normalize_merchant(row["merchant"] or "") == pattern:
            ids.append(int(row["id"]))

    if not ids:
        _upsert_merchant_rule(conn, merchant, category_id)
        return 0

    placeholders = ", ".join("?" for _ in ids)
    cursor = conn.execute(
        f"UPDATE transactions SET category_id = ? WHERE id IN ({placeholders})",
        (category_id, *ids),
    )
    _upsert_merchant_rule(conn, merchant, category_id)
    return int(cursor.rowcount)