"""Generación y envío del resumen diario de transacciones vía email."""

from __future__ import annotations

import logging
import smtplib
import sqlite3
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from utils import get_cycle_start_date

LOGGER = logging.getLogger(__name__)


def _format_clp(amount: int) -> str:
    """Formatea monto CLP con separadores de miles estilo chileno."""
    return f"${abs(amount):,.0f}".replace(",", ".")


def _build_html_report(report_date: date, partial: bool = False) -> str:
    """Genera el cuerpo HTML del reporte con transacciones del día y acumulado del ciclo."""

    cycle_start = get_cycle_start_date(report_date)

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Transacciones del día reportado (solo gastos y cargos, amount > 0)
        day_rows = conn.execute(
            """
            SELECT t.bank, t.merchant, t.type, t.amount, t.date,
                   COALESCE(c.name, 'Sin categoría') AS category
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE DATE(t.date) = ? AND t.amount > 0
            ORDER BY t.date, t.bank, category
            """,
            (report_date.isoformat(),),
        ).fetchall()

        # Acumulado del ciclo por categoría (solo gastos)
        cycle_rows = conn.execute(
            """
            SELECT COALESCE(c.name, 'Sin categoría') AS category,
                   SUM(t.amount) AS total
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE DATE(t.date) >= ? AND t.amount > 0
            GROUP BY category
            ORDER BY total DESC
            """,
            (cycle_start.isoformat(),),
        ).fetchall()

        # Gasto diario de los últimos 10 días
        last10_rows = conn.execute(
            """
            SELECT DATE(t.date) AS day, SUM(t.amount) AS total
            FROM transactions t
            WHERE DATE(t.date) > DATE(?, '-10 days') AND t.amount > 0
            GROUP BY day
            ORDER BY day DESC
            """,
            (report_date.isoformat(),),
        ).fetchall()
    finally:
        conn.close()

    total_day = sum(r["amount"] for r in day_rows)
    total_cycle = sum(r["total"] for r in cycle_rows)

    day_label = report_date.strftime("%d/%m/%Y")
    cycle_label = cycle_start.strftime("%d/%m/%Y")
    h2_title = (
        f"Resumen de hoy &mdash; {day_label} (hasta ahora)"
        if partial
        else f"Resumen financiero &mdash; {day_label}"
    )

    if day_rows:
        day_rows_html = "\n".join(
            f"<tr>"
            f"<td>{r['date'][8:10]}/{r['date'][5:7]} {r['date'][11:16]}</td>"
            f"<td>{r['bank']}</td>"
            f"<td>{r['merchant']}</td>"
            f"<td>{r['type']}</td>"
            f"<td>{r['category']}</td>"
            f"<td class='num'>{_format_clp(r['amount'])}</td>"
            f"</tr>"
            for r in day_rows
        )
    else:
        day_rows_html = (
            '<tr><td colspan="6" class="empty">Sin transacciones registradas</td></tr>'
        )

    cycle_rows_html = "\n".join(
        f"<tr><td>{r['category']}</td><td class='num'>{_format_clp(r['total'])}</td></tr>"
        for r in cycle_rows
    ) or '<tr><td colspan="2" class="empty">Sin gastos en el ciclo</td></tr>'

    last10_rows_html = "\n".join(
        f"<tr><td>{r['day'][8:10]}/{r['day'][5:7]}/{r['day'][0:4]}</td>"
        f"<td class='num'>{_format_clp(r['total'])}</td></tr>"
        for r in last10_rows
    ) or '<tr><td colspan="2" class="empty">Sin datos</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>
    body  {{ font-family: Arial, sans-serif; color: #222; max-width: 680px;
             margin: 0 auto; padding: 20px; }}
    h2   {{ color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 6px; }}
    h3   {{ color: #2874a6; margin-top: 28px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 8px; }}
    th   {{ background: #1a5276; color: #fff; padding: 8px 12px; text-align: left; }}
    td   {{ padding: 7px 12px; border-bottom: 1px solid #e8e8e8; }}
    .num  {{ text-align: right; }}
    .total-row td {{ font-weight: bold; background: #eaf2fb; }}
    .empty {{ text-align: center; color: #888; font-style: italic; }}
    .footer {{ margin-top: 32px; color: #aaa; font-size: 11px; }}
  </style>
</head>
<body>
  <h2>{h2_title}</h2>

  <h3>Transacciones del {day_label}</h3>
  <table>
    <tr>
      <th>Fecha</th><th>Banco</th><th>Comercio</th><th>Tipo</th><th>Categor&iacute;a</th><th>Monto</th>
    </tr>
    {day_rows_html}
    <tr class="total-row">
      <td colspan="5"><b>Total del d&iacute;a</b></td>
      <td class="num"><b>{_format_clp(total_day)}</b></td>
    </tr>
  </table>

  <h3>Acumulado del ciclo (desde {cycle_label})</h3>
  <table>
    <tr><th>Categor&iacute;a</th><th>Monto</th></tr>
    {cycle_rows_html}
    <tr class="total-row">
      <td><b>Total acumulado</b></td>
      <td class="num"><b>{_format_clp(total_cycle)}</b></td>
    </tr>
  </table>

  <h3>Gasto diario &mdash; &uacute;ltimos 10 d&iacute;as</h3>
  <table>
    <tr><th>D&iacute;a</th><th>Total gastado</th></tr>
    {last10_rows_html}
  </table>

  <p class="footer">Generado autom&aacute;ticamente por EconomicScript &middot; {day_label}</p>
</body>
</html>"""


def send_daily_report(report_date: date | None = None, partial: bool = False) -> None:
    """Genera y envía el reporte diario por email vía SMTP (Gmail TLS).

    Args:
        report_date: Fecha a reportar. Por defecto: ayer.
        partial: True para ejecución vespertina (reporta el día en curso, aún incompleto).
    """
    if report_date is None:
        report_date = date.today() if partial else date.today() - timedelta(days=1)

    smtp_to = config.SMTP_TO
    if not smtp_to:
        LOGGER.warning(
            "SMTP_TO no configurado en .env — no se enviará el reporte. "
            "Agrega SMTP_TO=tu_correo@gmail.com al archivo .env"
        )
        return

    smtp_user = config.SMTP_USER or config.IMAP_USER
    smtp_password = config.SMTP_PASSWORD

    if not smtp_user or not smtp_password:
        LOGGER.error(
            "Credenciales SMTP no disponibles. "
            "Configura SMTP_USER/SMTP_PASSWORD en .env (usa una App Password de Google)"
        )
        return

    html_body = _build_html_report(report_date, partial=partial)
    day_label = report_date.strftime("%d/%m/%Y")
    subject_suffix = " (hoy - parcial)" if partial else ""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[EconomicScript] Resumen {day_label}{subject_suffix}"
    msg["From"] = smtp_user
    msg["To"] = smtp_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [smtp_to], msg.as_string())
        LOGGER.info("Reporte del %s enviado a %s", day_label, smtp_to)
    except Exception as exc:
        LOGGER.error("Error al enviar reporte del %s: %s", day_label, exc)
        raise
