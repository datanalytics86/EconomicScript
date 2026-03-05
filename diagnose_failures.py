"""Diagnóstico de correos fallidos almacenados en unprocessed_emails.

Muestra samples de cuerpos de email que no pudieron ser parseados,
agrupados por banco, para identificar layouts nuevos.

Uso:
    python diagnose_failures.py
    python diagnose_failures.py --banco BCI --limit 10
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

import config

SEPARATOR = "=" * 70
SUBSEP = "-" * 70


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnóstico de correos fallidos")
    ap.add_argument("--banco", help="Filtrar por banco (BCI, BANCO_ESTADO, Security)")
    ap.add_argument("--limit", type=int, default=5, help="Muestras por banco (default: 5)")
    ap.add_argument("--full", action="store_true", help="Mostrar body completo (sin truncar)")
    args = ap.parse_args()

    db_path = config.DB_PATH or "finance.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Resumen general
    print(SEPARATOR)
    print("RESUMEN unprocessed_emails")
    print(SEPARATOR)
    for row in conn.execute(
        "SELECT error_reason, COUNT(*) as n FROM unprocessed_emails GROUP BY error_reason ORDER BY n DESC"
    ):
        print(f"  [{row['n']:>4}]  {row['error_reason']}")

    print()

    # Determinar grupos a mostrar
    if args.banco:
        grupos = [(args.banco, f"%{args.banco}%")]
    else:
        grupos = [
            ("BCI", "%bci%"),
            ("BancoEstado", "%banco estado%"),
            ("Security", "%security%"),
        ]

    for nombre, sender_pattern in grupos:
        rows = conn.execute(
            """
            SELECT gmail_message_id, sender, subject, raw_text, error_reason
            FROM unprocessed_emails
            WHERE sender LIKE ? AND error_reason LIKE '%No fue posible%'
            ORDER BY rowid DESC
            LIMIT ?
            """,
            (sender_pattern, args.limit),
        ).fetchall()

        print(SEPARATOR)
        print(f"BANCO: {nombre}  ({len(rows)} muestras recientes)")
        print(SEPARATOR)

        if not rows:
            print("  (sin registros)\n")
            continue

        for r in rows:
            print(f"\n{SUBSEP}")
            print(f"UID     : {r['gmail_message_id']}")
            print(f"From    : {r['sender']}")
            print(f"Subject : {r['subject']}")
            print(f"Error   : {r['error_reason']}")
            body = r["raw_text"] or ""
            if not args.full:
                body = body[:800] + ("…" if len(r["raw_text"] or "") > 800 else "")
            print(f"Body ({len(r['raw_text'] or '')} chars):")
            print("<<<")
            print(body)
            print(">>>")

        print()

    conn.close()


if __name__ == "__main__":
    main()
