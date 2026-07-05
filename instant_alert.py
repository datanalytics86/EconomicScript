"""Alertas instantáneas por email cuando se detectan transacciones nuevas."""

from __future__ import annotations

import logging
import smtplib
import sqlite3
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

LOGGER = logging.getLogger(__name__)


def _format_clp(amount: int) -> str:
    return f"${abs(amount):,.0f}".replace(",", ".")


def _fetch_transactions(transaction_ids: list[int]) -> list[sqlite3.Row]:
    if not transaction_ids:
        return []
    placeholders = ",".join("?" * len(transaction_ids))
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            f"""
            SELECT t.id, t.bank, t.merchant, t.type, t.amount, t.date,
                   COALESCE(c.name, 'Sin categoría') AS category
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id IN ({placeholders})
            ORDER BY t.date DESC
            """,
            transaction_ids,
        ).fetchall()
    finally:
        conn.close()


def _build_html(rows: list[sqlite3.Row]) -> str:
    total = sum(r["amount"] for r in rows if r["amount"] > 0)
    items_html = "\n".join(
        f"<tr>"
        f"<td>{r['date'][8:10]}/{r['date'][5:7]} {r['date'][11:16]}</td>"
        f"<td>{r['bank']}</td>"
        f"<td>{r['merchant']}</td>"
        f"<td>{r['type']}</td>"
        f"<td>{r['category']}</td>"
        f"<td class='num'>{_format_clp(r['amount'])}</td>"
        f"</tr>"
        for r in rows
    )
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>
    body  {{ font-family: Arial, sans-serif; color: #222; max-width: 680px;
             margin: 0 auto; padding: 20px; }}
    h2   {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 6px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th   {{ background: #c0392b; color: #fff; padding: 8px 12px; text-align: left; }}
    td   {{ padding: 7px 12px; border-bottom: 1px solid #e8e8e8; }}
    .num  {{ text-align: right; font-weight: bold; }}
    .footer {{ margin-top: 24px; color: #aaa; font-size: 11px; }}
  </style>
</head>
<body>
  <h2>Nueva transacción detectada</h2>
  <p>Se registraron <b>{len(rows)}</b> movimiento(s) nuevo(s):</p>
  <table>
    <tr>
      <th>Fecha</th><th>Banco</th><th>Comercio</th><th>Tipo</th><th>Categoría</th><th>Monto</th>
    </tr>
    {items_html}
  </table>
  <p>Total: <b>{_format_clp(total)}</b></p>
  <p class="footer">EconomicScript · alerta automática · {now}</p>
</body>
</html>"""


def send_instant_alert(transaction_ids: list[int]) -> None:
    """Envía email inmediato con las transacciones recién insertadas."""
    if not transaction_ids:
        return

    smtp_to = config.SMTP_TO
    if not smtp_to:
        LOGGER.warning("SMTP_TO no configurado — alerta instantánea omitida")
        return

    smtp_user = config.SMTP_USER or config.IMAP_USER
    smtp_password = config.SMTP_PASSWORD
    if not smtp_user or not smtp_password:
        LOGGER.error("Credenciales SMTP no disponibles — alerta instantánea omitida")
        return

    rows = _fetch_transactions(transaction_ids)
    if not rows:
        return

    html_body = _build_html(rows)
    merchants = ", ".join(r["merchant"][:30] for r in rows[:3])
    if len(rows) > 3:
        merchants += f" (+{len(rows) - 3} más)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[EconomicScript] {len(rows)} transacción(es) nueva(s): {merchants}"
    msg["From"] = smtp_user
    msg["To"] = smtp_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [smtp_to], msg.as_string())
        LOGGER.info("Alerta instantánea enviada (%d transacciones) → %s", len(rows), smtp_to)
    except Exception as exc:
        LOGGER.error("Error enviando alerta instantánea: %s", exc)
        raise