"""Corrige en BD las anulaciones TC mal parseadas como Compra TC positivas.

Detecta por raw_text (BCI: "anulación nacional", etc.) y:
  - type  → 'Anulación TC'
  - amount → -ABS(amount)

Idempotente: solo toca filas con amount > 0 y type distinto de Anulación TC.

Uso:
    python scripts/fix_anulaciones.py
    python scripts/fix_anulaciones.py --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from categorizer import auto_categorize  # noqa: E402

# Misma lógica que parsers: texto real de BCI y variantes
_ANUL_SQL = """
    (
        lower(raw_text) LIKE '%anulación nacional%'
        OR lower(raw_text) LIKE '%anulacion nacional%'
        OR lower(raw_text) LIKE '%anulación internacional%'
        OR lower(raw_text) LIKE '%anulacion internacional%'
        OR lower(raw_text) LIKE '%anulación de tarjeta%'
        OR lower(raw_text) LIKE '%anulacion de tarjeta%'
        OR lower(raw_text) LIKE '%realizaste una%anulación%'
        OR lower(raw_text) LIKE '%realizaste una%anulacion%'
        OR lower(raw_text) LIKE '%reverso de compra%'
        OR lower(raw_text) LIKE '%reverso nacional%'
    )
"""


def main() -> None:
    p = argparse.ArgumentParser(description="Fix anulaciones TC mal parseadas")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra cuántas filas se corregirían, sin escribir.",
    )
    args = p.parse_args()

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        candidates = conn.execute(
            f"""
            SELECT id, date, amount, type, merchant, bank
            FROM transactions
            WHERE amount > 0
              AND type != 'Anulación TC'
              AND {_ANUL_SQL}
            ORDER BY date DESC
            """
        ).fetchall()

        print(f"Candidatas a corregir: {len(candidates)}")
        for r in candidates[:15]:
            print(
                f"  id={r['id']} {r['date'][:10]} {r['bank']} "
                f"{r['type']} ${r['amount']:,} → Anulación TC $-{r['amount']:,} "
                f"| {r['merchant'][:50]}"
            )
        if len(candidates) > 15:
            print(f"  … y {len(candidates) - 15} más")

        if args.dry_run:
            print("Dry-run: no se escribió nada.")
            return

        if not candidates:
            print("Nada que corregir.")
            return

        cur = conn.execute(
            f"""
            UPDATE transactions
            SET type = 'Anulación TC',
                amount = -ABS(amount)
            WHERE amount > 0
              AND type != 'Anulación TC'
              AND {_ANUL_SQL}
            """
        )
        updated = cur.rowcount
        conn.commit()
        print(f"Actualizadas: {updated} filas → type=Anulación TC, amount negativo")

        n = auto_categorize(conn)
        conn.commit()
        print(f"Auto-categorizadas (pasada extra): {n}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
