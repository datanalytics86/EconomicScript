"""Generación y envío del resumen diario de transacciones vía email."""

from __future__ import annotations

import logging
import smtplib
import sqlite3
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from categorizer import auto_categorize
from report_utils import (
    build_category_groups_html,
    build_uncategorized_html,
    fetch_transactions_grouped,
    fetch_uncategorized_expenses,
    get_connection,
)
from utils import NON_CONSUMPTION_TYPES, get_cycle_start_date

LOGGER = logging.getLogger(__name__)


def _format_clp(amount: int) -> str:
    """Formatea monto CLP con separadores de miles estilo chileno."""
    return f"${abs(amount):,.0f}".replace(",", ".")


def _build_html_report(report_date: date, partial: bool = False) -> str:
    """Genera el cuerpo HTML del reporte con transacciones del día y acumulado del ciclo."""

    cycle_start = get_cycle_start_date(report_date)

    conn = get_connection()
    try:
        # Aplica reglas aprendidas antes del residual, para no listar lo ya resoluble
        n_auto = auto_categorize(conn)
        if n_auto:
            conn.commit()
            LOGGER.info("Auto-categorizadas %s transacciones antes del reporte", n_auto)

        day_groups = fetch_transactions_grouped(
            conn, since=report_date, until=report_date, expenses_only=True
        )
        cycle_groups = fetch_transactions_grouped(
            conn, since=cycle_start, until=report_date, expenses_only=True
        )

        day_rows = [r for g in day_groups for r in g.transactions]
        cycle_rows = [{"category": g.category, "total": g.total} for g in cycle_groups]

        day_by_category_html = build_category_groups_html(
            day_groups,
            title=f"Gastos del {report_date.strftime('%d/%m/%Y')} por categor\u00eda",
            empty_message="Sin transacciones registradas",
        )
        cycle_by_category_html = build_category_groups_html(
            cycle_groups,
            title=f"Gastos del ciclo (desde {cycle_start.strftime('%d/%m/%Y')}) por categor\u00eda",
            empty_message="Sin gastos en el ciclo",
        )

        uncategorized_day = fetch_uncategorized_expenses(
            conn, since=report_date, until=report_date
        )
        uncategorized_html = build_uncategorized_html(
            uncategorized_day,
            title="Pendientes de categorizar (hoy)",
            dashboard_url=config.DASHBOARD_URL or None,
        )

        # Gasto diario de los últimos 10 días (gasto real de consumo + dedupe fuentes)
        non_consumption = sorted(NON_CONSUMPTION_TYPES)
        placeholders = ", ".join("?" for _ in non_consumption)
        last10_rows = conn.execute(
            f"""
            SELECT DATE(t.date) AS day, SUM(t.amount) AS total
            FROM transactions t
            WHERE DATE(t.date) > DATE(?, '-10 days') AND t.amount > 0
              AND (t.type IS NULL OR t.type NOT IN ({placeholders}))
              AND (t.source = 'gmail' OR (t.source = 'cartola' AND COALESCE(t.verified, 0) = 0))
            GROUP BY day
            ORDER BY day DESC
            """,
            (report_date.isoformat(), *non_consumption),
        ).fetchall()
    finally:
        conn.close()

    total_day = sum(r["amount"] for r in day_rows)
    total_cycle = sum(r["total"] for r in cycle_rows)
    n_uncat = len(uncategorized_day)

    day_label = report_date.strftime("%d/%m/%Y")
    cycle_label = cycle_start.strftime("%d/%m/%Y")
    h2_title = (
        f"Resumen de hoy &mdash; {day_label} (hasta ahora)"
        if partial
        else f"Resumen financiero &mdash; {day_label}"
    )
    if n_uncat:
        h2_title += f" &middot; {n_uncat} sin categor\u00eda"

    last10_map = {r['day']: r['total'] for r in last10_rows}
    last10_days = [report_date - timedelta(days=i) for i in range(10)]
    last10_rows_html = "\n".join(
        f"<tr><td>{d.strftime('%d/%m/%Y')}</td>"
        f"<td class='num'>{_format_clp(last10_map.get(d.isoformat(), 0))}</td></tr>"
        for d in last10_days
    )

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
    .cat-block {{ margin: 20px 0 28px; padding: 12px; background: #f8fbff;
                  border-left: 4px solid #2874a6; border-radius: 4px; }}
    .cat-block h4 {{ margin: 0 0 10px; color: #1a5276; }}
    .summary-table {{ margin-bottom: 24px; }}
    .subtotal-row td {{ background: #f4f8fc; font-size: 0.95em; }}
  </style>
</head>
<body>
  <h2>{h2_title}</h2>

  {uncategorized_html}

  <hr style="margin:32px 0;border:none;border-top:2px solid #e0e0e0;">

  {day_by_category_html}

  <p class="total-row" style="padding:10px 12px;background:#eaf2fb;border-radius:4px;">
    <b>Total del d&iacute;a: {_format_clp(total_day)}</b>
  </p>

  <hr style="margin:32px 0;border:none;border-top:2px solid #e0e0e0;">

  {cycle_by_category_html}

  <p class="total-row" style="padding:10px 12px;background:#eaf2fb;border-radius:4px;">
    <b>Total acumulado del ciclo (desde {cycle_label}): {_format_clp(total_cycle)}</b>
  </p>

  <h3>Gasto diario &mdash; &uacute;ltimos 10 d&iacute;as</h3>
  <table>
    <tr><th>D&iacute;a</th><th>Total gastado</th></tr>
    {last10_rows_html}
  </table>

  <p class="footer">Generado autom&aacute;ticamente por EconomicScript &middot; {day_label}</p>
</body>
</html>"""


def send_daily_report(
    report_date: date | None = None,
    partial: bool = False,
    slot_label: str | None = None,
) -> None:
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
    if slot_label:
        subject_suffix = f" — {slot_label}"
    elif partial:
        subject_suffix = " (hoy - parcial)"
    else:
        subject_suffix = ""

    # Aviso en el asunto si aún hay residual de categorización ese día
    try:
        conn_subj = get_connection()
        try:
            n_uncat_subj = len(
                fetch_uncategorized_expenses(
                    conn_subj, since=report_date, until=report_date
                )
            )
        finally:
            conn_subj.close()
    except Exception:
        n_uncat_subj = 0
    if n_uncat_subj:
        subject_suffix = f"{subject_suffix} · {n_uncat_subj} sin categoría"

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
