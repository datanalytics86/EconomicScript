"""Generación y envío del resumen diario de transacciones vía email."""

from __future__ import annotations

import logging
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from report_utils import (
    build_category_bars_html,
    build_category_groups_html,
    build_daily_bars_html,
    fetch_transactions_grouped,
    get_connection,
    net_lines_from_rows,
    fetch_raw_consumption,
)
from utils import (
    CONSUMPTION_SQL_FILTER,
    format_clp,
    get_cycle_label,
    get_cycle_start_date,
)

LOGGER = logging.getLogger(__name__)


def _format_clp(amount: int) -> str:
    return format_clp(amount)


def _build_html_report(report_date: date, partial: bool = False) -> str:
    """Cuerpo HTML: neto por comercio, KPIs de ciclo desde el 27, barras CSS."""

    cycle_start = get_cycle_start_date(report_date)
    cycle_name = get_cycle_label(report_date)  # ej. "Agosto"

    conn = get_connection()
    try:
        day_groups = fetch_transactions_grouped(
            conn, since=report_date, until=report_date, expenses_only=True, net_display=True
        )
        cycle_groups = fetch_transactions_grouped(
            conn, since=cycle_start, until=report_date, expenses_only=True, net_display=True
        )

        total_day = sum(g.total for g in day_groups)
        total_cycle = sum(g.total for g in cycle_groups)

        day_all_count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE DATE(date) = ?",
            (report_date.isoformat(),),
        ).fetchone()[0]
        # Ops crudas de consumo (incluye voids) vs líneas netas
        day_raw = fetch_raw_consumption(conn, since=report_date, until=report_date)
        day_net_lines = net_lines_from_rows(day_raw)
        n_day_net = len(day_net_lines)

        unprocessed_count = int(
            conn.execute("SELECT COUNT(*) FROM unprocessed_emails").fetchone()[0]
        )

        # Últimos 14 días — gasto neto diario
        last_n = 14
        last_rows = conn.execute(
            f"""
            SELECT DATE(t.date) AS day, t.merchant, t.type, t.amount, t.bank,
                   COALESCE(c.name, 'Sin categoría') AS category, t.date
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE DATE(t.date) > DATE(?, '-{last_n} days') AND DATE(t.date) <= ?
              AND ({CONSUMPTION_SQL_FILTER})
            ORDER BY t.date
            """,
            (report_date.isoformat(), report_date.isoformat()),
        ).fetchall()

        by_day_raw: dict[str, list] = {}
        for r in last_rows:
            by_day_raw.setdefault(r["day"], []).append(r)

        last_n_days = [report_date - timedelta(days=i) for i in range(last_n - 1, -1, -1)]
        day_totals: list[tuple[date, int]] = []
        for d in last_n_days:
            raw = by_day_raw.get(d.isoformat(), [])
            net = sum(L.amount for L in net_lines_from_rows(raw))
            day_totals.append((d, net))

        # Conteo ingestado por día (cualquier tipo)
        last_counts = {
            r["day"]: r["n"]
            for r in conn.execute(
                f"""
                SELECT DATE(date) AS day, COUNT(*) AS n
                FROM transactions
                WHERE DATE(date) > DATE(?, '-{last_n} days') AND DATE(date) <= ?
                GROUP BY day
                """,
                (report_date.isoformat(), report_date.isoformat()),
            ).fetchall()
        }
    finally:
        conn.close()

    day_label = report_date.strftime("%d/%m/%Y")
    cycle_from = cycle_start.strftime("%d/%m/%Y")
    h2_title = (
        f"Resumen de hoy &mdash; {day_label} <span class='badge'>parcial</span>"
        if partial
        else f"Resumen financiero &mdash; {day_label}"
    )

    ingest_warning = ""
    if day_all_count == 0:
        ingest_warning = (
            '<div class="alert-warn">'
            f"<b>⚠ 0 movimientos ingestados este d&iacute;a ({day_label})</b> — "
            "revisa ingesta Gmail / unprocessed_emails."
            "</div>"
        )

    day_detail = build_category_groups_html(
        day_groups,
        title=f"Gastos del d&iacute;a (neto por comercio)",
        empty_message="Sin gastos de consumo este d&iacute;a",
        show_detail=True,
    )
    cycle_detail = build_category_groups_html(
        cycle_groups,
        title=f"Detalle del ciclo {cycle_name}",
        empty_message="Sin gastos en el ciclo",
        show_detail=True,
    )
    cat_bars = build_category_bars_html(
        cycle_groups,
        title=f"Gr&aacute;fico &mdash; categor&iacute;as del ciclo {cycle_name}",
    )
    daily_bars = build_daily_bars_html(
        day_totals,
        title=f"Gr&aacute;fico &mdash; &uacute;ltimos {last_n} d&iacute;as (neto)",
    )

    # Tabla compacta últimos días
    last_table_rows = "\n".join(
        (
            f"<tr class='{'today-row' if d == report_date else ''}'>"
            f"<td>{d.strftime('%d/%m/%Y')}</td>"
            f"<td class='num'>{_format_clp(total)}</td>"
            f"<td class='muted'>"
            f"{'hoy' if d == report_date else ''}"
            f"{' · 0 ingestados' if last_counts.get(d.isoformat(), 0) == 0 else ''}"
            f"</td></tr>"
        )
        for d, total in reversed(day_totals)
    )

    unprocessed_note = (
        f'<p class="footer-note">Correos en cola unprocessed: <b>{unprocessed_count}</b></p>'
        if unprocessed_count
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      color: #1c2833; background: #f0f3f7; margin: 0; padding: 0;
    }}
    .wrap {{ max-width: 640px; margin: 0 auto; padding: 20px 12px 40px; }}
    .header {{
      background: linear-gradient(135deg, #0e4d7b 0%, #1a6fa8 55%, #2e86c1 100%);
      color: #fff; border-radius: 16px; padding: 22px 24px 20px; margin-bottom: 16px;
    }}
    .header h1 {{ margin: 0 0 6px; font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }}
    .header .sub {{ opacity: 0.9; font-size: 13px; }}
    .badge {{
      display: inline-block; background: rgba(255,255,255,0.22); font-size: 11px;
      padding: 2px 8px; border-radius: 99px; font-weight: 600; vertical-align: middle;
    }}
    .kpi-row {{ width: 100%; border-collapse: separate; border-spacing: 10px 0; margin: 14px -10px 0; }}
    .kpi {{
      background: rgba(255,255,255,0.14); border-radius: 12px; padding: 12px 14px;
      text-align: left; width: 50%;
    }}
    .kpi .lbl {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.85; }}
    .kpi .val {{ font-size: 22px; font-weight: 700; margin-top: 4px; letter-spacing: -0.02em; }}
    .kpi .hint {{ font-size: 11px; opacity: 0.8; margin-top: 2px; }}
    .card {{
      background: #fff; border-radius: 14px; padding: 16px 18px; margin: 14px 0;
      box-shadow: 0 1px 3px rgba(15, 40, 70, 0.06);
    }}
    h3 {{ color: #0e4d7b; font-size: 15px; margin: 0 0 12px; }}
    h4 {{ margin: 0 0 10px; color: #0e4d7b; font-size: 14px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 4px; }}
    th {{
      background: #0e4d7b; color: #fff; padding: 8px 10px; text-align: left;
      font-size: 12px; font-weight: 600;
    }}
    td {{ padding: 7px 10px; border-bottom: 1px solid #eef1f5; font-size: 13px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .muted {{ color: #8a96a3; font-size: 12px; }}
    .hint {{ color: #8a96a3; font-size: 11px; font-weight: 400; }}
    .total-row td {{ font-weight: 700; background: #eaf2fb; }}
    .subtotal-row td {{ background: #f6f9fc; font-size: 0.95em; }}
    .today-row td {{ background: #e8f6ef; }}
    .empty {{ text-align: center; color: #8a96a3; font-style: italic; padding: 16px; }}
    .cat-block {{
      margin: 14px 0; padding: 12px 14px; background: #f7fafc;
      border-left: 4px solid #1a6fa8; border-radius: 0 10px 10px 0;
    }}
    .summary-table {{ margin-bottom: 8px; }}
    .alert-warn {{
      padding: 12px 14px; background: #fff8e6; border-left: 4px solid #e67e22;
      border-radius: 8px; color: #7d6608; margin: 12px 0; font-size: 13px;
    }}
    .footer {{ margin-top: 20px; color: #a0aab4; font-size: 11px; text-align: center; }}
    .footer-note {{ color: #a0aab4; font-size: 11px; }}
    .pill {{
      display: inline-block; background: #e8f4fc; color: #0e4d7b; font-size: 12px;
      padding: 4px 10px; border-radius: 99px; font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <h1>{h2_title}</h1>
      <div class="sub">
        Montos <b>netos</b> (preautorizaciones y anulaciones ya consolidadas) ·
        sin transferencias ni pagos de tarjeta
      </div>
      <table class="kpi-row" role="presentation"><tr>
        <td class="kpi">
          <div class="lbl">Total del d&iacute;a</div>
          <div class="val">{_format_clp(total_day)}</div>
          <div class="hint">{n_day_net} comercios · {day_all_count} mov. BD</div>
        </td>
        <td class="kpi">
          <div class="lbl">Total acumulado {cycle_name}</div>
          <div class="val">{_format_clp(total_cycle)}</div>
          <div class="hint">desde el {cycle_from} (d&iacute;a 27)</div>
        </td>
      </tr></table>
    </div>

    {ingest_warning}

    <div class="card" style="text-align:center;padding:14px;">
      <span class="pill">Ciclo {cycle_name}: {_format_clp(total_cycle)}</span>
      <div class="muted" style="margin-top:8px;">
        Acumulado de consumo neto desde el <b>{cycle_from}</b> hasta el <b>{day_label}</b>
      </div>
    </div>

    {cat_bars}

    {daily_bars}

    {day_detail}

    <div class="card" style="background:#eaf2fb;">
      <div style="font-size:13px;color:#5d6d7e;">Total del d&iacute;a (neto)</div>
      <div style="font-size:26px;font-weight:700;color:#0e4d7b;">{_format_clp(total_day)}</div>
    </div>

    {cycle_detail}

    <div class="card" style="background:linear-gradient(135deg,#0e4d7b,#1a6fa8);color:#fff;">
      <div style="font-size:12px;opacity:0.9;text-transform:uppercase;letter-spacing:0.05em;">
        Total acumulado {cycle_name}
      </div>
      <div style="font-size:28px;font-weight:700;margin:6px 0;">{_format_clp(total_cycle)}</div>
      <div style="font-size:12px;opacity:0.85;">
        Ciclo desde el {cycle_from} (corte d&iacute;a 27 de cada mes)
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Tabla &mdash; &uacute;ltimos {last_n} d&iacute;as</h3>
      <table>
        <tr><th>D&iacute;a</th><th>Total neto</th><th></th></tr>
        {last_table_rows}
      </table>
    </div>

    {unprocessed_note}
    <p class="footer">
      EconomicScript &middot; {day_label}<br>
      Anulaciones y preauth se netean por comercio (ej. 1000−990 = 10). No se listan voids.
    </p>
  </div>
</body>
</html>"""


def send_daily_report(
    report_date: date | None = None,
    partial: bool = False,
    slot_label: str | None = None,
) -> None:
    """Genera y envía el reporte diario por email vía SMTP (Gmail TLS)."""
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
    cycle_name = get_cycle_label(report_date)
    if slot_label:
        subject_suffix = f" — {slot_label}"
    elif partial:
        subject_suffix = " (hoy - parcial)"
    else:
        subject_suffix = ""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"[EconomicScript] {day_label} · ciclo {cycle_name}{subject_suffix}"
    )
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
