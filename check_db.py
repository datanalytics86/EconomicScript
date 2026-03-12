"""Diagnóstico de estado de la base de datos: unprocessed_emails y transacciones por día."""
from __future__ import annotations

import config
from db import Database


def main() -> None:
    db = Database(config.DB_PATH)
    conn = db.connect()
    try:
        # --- unprocessed_emails ---
        rows = conn.execute(
            "SELECT id, DATE(created_at) AS day, sender, subject, error_reason "
            "FROM unprocessed_emails ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        print(f"=== Correos sin procesar: {len(rows)} (últimos 50) ===")
        for r in rows:
            print(f"  [{r['day']}] id={r['id']} sender={r['sender']}")
            print(f"    subject : {r['subject']}")
            print(f"    error   : {r['error_reason']}")

        # --- transacciones por día/banco ---
        rows2 = conn.execute(
            "SELECT DATE(date) AS day, bank, COUNT(*) AS n, SUM(amount) AS total "
            "FROM transactions "
            "WHERE amount > 0 "
            "GROUP BY DATE(date), bank "
            "ORDER BY day DESC "
            "LIMIT 40"
        ).fetchall()
        print(f"\n=== Transacciones por día/banco (últimos 40 registros) ===")
        for r in rows2:
            print(f"  {r['day']}  {r['bank']:<14} {r['n']:>4} txs   ${r['total']:>12,.0f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
