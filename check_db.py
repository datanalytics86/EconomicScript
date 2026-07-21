"""Diagnóstico de estado de la base de datos: unprocessed_emails y transacciones por día."""
from __future__ import annotations

import config
from db import Database


def main() -> None:
    import sys
    dump_id = int(sys.argv[1]) if len(sys.argv) > 1 else None

    db = Database(config.DB_PATH)
    conn = db.connect()
    try:
        # --- modo dump: muestra raw_text de un email específico ---
        if dump_id is not None:
            row = conn.execute(
                "SELECT id, sender, subject, error_reason, raw_text "
                "FROM unprocessed_emails WHERE id = ?",
                (dump_id,),
            ).fetchone()
            if not row:
                print(f"No existe unprocessed_emails.id={dump_id}")
                return
            print(f"id={row['id']} sender={row['sender']}")
            print(f"subject : {row['subject']}")
            print(f"error   : {row['error_reason']}")
            print(f"--- raw_text ({len(row['raw_text'])} chars) ---")
            print(row["raw_text"])
            return

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

        # --- gasto real de consumo por día/banco (sin transferencias/pagos TC + dedupe) ---
        from utils import NON_CONSUMPTION_TYPES

        types = sorted(NON_CONSUMPTION_TYPES)
        ph = ", ".join("?" for _ in types)
        rows2 = conn.execute(
            f"""
            SELECT DATE(date) AS day, bank, COUNT(*) AS n, SUM(amount) AS total
            FROM transactions
            WHERE amount > 0
              AND (type IS NULL OR type NOT IN ({ph}))
              AND (source = 'gmail' OR (source = 'cartola' AND COALESCE(verified, 0) = 0))
            GROUP BY DATE(date), bank
            ORDER BY day DESC
            LIMIT 40
            """,
            types,
        ).fetchall()
        print("\n=== Gasto real por día/banco (últimos 40 grupos) ===")
        for r in rows2:
            print(f"  {r['day']}  {r['bank']:<14} {r['n']:>4} txs   ${r['total']:>12,.0f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
