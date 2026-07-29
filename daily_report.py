"""Generación y envío del resumen diario de transacciones vía email.

Diseño deliberadamente minimalista (tier 1):
  1. Total del día
  2. Total acumulado del ciclo (desde el 27 → etiqueta mes, ej. Agosto)
  3. En qué se ha gastado: solo categorías netas (sin comercios ni anulaciones)

No se listan movimientos, preauth/voids ni transferencias.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from report_utils import CategoryGroup, fetch_transactions_grouped, get_connection
from utils import format_clp, get_cycle_label, get_cycle_start_date

LOGGER = logging.getLogger(__name__)


def _format_clp(amount: int) -> str:
    return format_clp(amount)


def _category_breakdown_html(
    groups: list[CategoryGroup],
    *,
    title: str,
    empty: str = "Sin gasto de consumo",
) -> str:
    """Solo categorías: barra + monto + % del total. Sin comercios."""
    positives = [g for g in groups if g.total > 0]
    if not positives:
        return f'<p style="color:#8a96a3;font-style:italic;margin:8px 0;">{empty}</p>'

    grand = sum(g.total for g in positives)
    max_amt = max(g.total for g in positives)
    rows: list[str] = []
    for g in positives:
        pct = g.total / grand * 100 if grand else 0
        bar = 0 if max_amt <= 0 else min(100, int(round(g.total / max_amt * 100)))
        if bar < 3 and g.total > 0:
            bar = 3
        rows.append(
            f"""
<tr>
  <td style="padding:10px 0 4px;font-size:14px;color:#1c2833;font-weight:600;">
    {g.category}
  </td>
  <td style="padding:10px 0 4px;text-align:right;font-size:14px;font-weight:700;
             color:#0e4d7b;white-space:nowrap;">{_format_clp(g.total)}</td>
  <td style="padding:10px 0 4px 12px;text-align:right;font-size:12px;color:#8a96a3;
             width:48px;">{pct:.0f}%</td>
</tr>
<tr>
  <td colspan="3" style="padding:0 0 10px;">
    <div style="background:#eef2f6;border-radius:6px;height:10px;overflow:hidden;">
      <div style="width:{bar}%;background:#1a6fa8;height:10px;border-radius:6px;"></div>
    </div>
  </td>
</tr>"""
        )

    return f"""
<div style="margin-top:4px;">
  <div style="font-size:13px;font-weight:700;color:#0e4d7b;margin-bottom:8px;
              text-transform:uppercase;letter-spacing:0.04em;">{title}</div>
  <table style="width:100%;border-collapse:collapse;">{''.join(rows)}</table>
</div>"""


def _build_html_report(report_date: date, partial: bool = False) -> str:
    """Email corto: hoy + acumulado del mes + desglose por categoría."""

    cycle_start = get_cycle_start_date(report_date)
    cycle_name = get_cycle_label(report_date)

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
    finally:
        conn.close()

    day_label = report_date.strftime("%d/%m/%Y")
    cycle_from = cycle_start.strftime("%d/%m")
    partial_note = " · parcial" if partial else ""

    warn = ""
    if day_all_count == 0:
        warn = (
            '<p style="margin:12px 0 0;padding:10px 12px;background:#fff8e6;'
            'border-radius:8px;color:#7d6608;font-size:13px;">'
            "Sin movimientos ingestados hoy — revisa Gmail/ingesta."
            "</p>"
        )

    day_block = _category_breakdown_html(
        day_groups,
        title=f"Hoy · {day_label}",
        empty="Sin gasto de consumo hoy",
    )
    cycle_block = _category_breakdown_html(
        cycle_groups,
        title=f"En qu&eacute; se ha gastado · {cycle_name}",
        empty=f"Sin gasto en el ciclo {cycle_name}",
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f0f3f7;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:480px;margin:0 auto;padding:24px 16px 40px;">

    <!-- Totales -->
    <div style="background:linear-gradient(145deg,#0e4d7b 0%,#1a6fa8 100%);
                color:#fff;border-radius:16px;padding:22px 22px 18px;">
      <div style="font-size:13px;opacity:0.85;margin-bottom:14px;">
        {day_label}{partial_note}
      </div>
      <table style="width:100%;border-collapse:collapse;" role="presentation">
        <tr>
          <td style="width:50%;padding:0 10px 0 0;vertical-align:top;">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;opacity:0.8;">
              Hoy
            </div>
            <div style="font-size:26px;font-weight:700;margin-top:4px;letter-spacing:-0.02em;">
              {_format_clp(total_day)}
            </div>
          </td>
          <td style="width:50%;padding:0 0 0 10px;vertical-align:top;
                     border-left:1px solid rgba(255,255,255,0.2);">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;opacity:0.8;
                        padding-left:12px;">
              Acumulado {cycle_name}
            </div>
            <div style="font-size:26px;font-weight:700;margin-top:4px;letter-spacing:-0.02em;
                        padding-left:12px;">
              {_format_clp(total_cycle)}
            </div>
            <div style="font-size:11px;opacity:0.75;margin-top:4px;padding-left:12px;">
              desde el {cycle_from}
            </div>
          </td>
        </tr>
      </table>
      {warn}
    </div>

    <!-- Mes: en qué se gastó -->
    <div style="background:#fff;border-radius:14px;padding:18px 20px;margin-top:14px;
                box-shadow:0 1px 3px rgba(15,40,70,0.06);">
      {cycle_block}
      <div style="margin-top:14px;padding-top:12px;border-top:1px solid #eef1f5;
                  display:flex;justify-content:space-between;align-items:baseline;">
        <span style="font-size:13px;color:#5d6d7e;">Total {cycle_name}</span>
        <span style="font-size:18px;font-weight:700;color:#0e4d7b;">{_format_clp(total_cycle)}</span>
      </div>
    </div>

    <!-- Hoy por categoría (solo si hay algo) -->
    <div style="background:#fff;border-radius:14px;padding:18px 20px;margin-top:14px;
                box-shadow:0 1px 3px rgba(15,40,70,0.06);">
      {day_block}
    </div>

    <p style="text-align:center;color:#a0aab4;font-size:11px;margin:20px 0 0;">
      Solo gasto de consumo · transferencias y pagos de tarjeta excluidos · anulaciones neteadas
    </p>
  </div>
</body>
</html>"""


def _month_range(year: int, month: int, until: date) -> tuple[date, date]:
    """Primer y último día del mes (acotado a until)."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    if end > until:
        end = until
    return start, end


def _build_digest_html(*, since: date, until: date) -> str:
    """Digest tier 1: total del período, por mes y por categoría. Sin comercios."""
    from utils import MONTHS_ES

    conn = get_connection()
    try:
        all_groups = fetch_transactions_grouped(
            conn, since=since, until=until, expenses_only=True, net_display=True
        )
        total_all = sum(g.total for g in all_groups)

        month_rows: list[tuple[str, int]] = []
        y, m = since.year, since.month
        while date(y, m, 1) <= until:
            m_start, m_end = _month_range(y, m, until)
            if m_end >= since:
                m_start = max(m_start, since)
                groups = fetch_transactions_grouped(
                    conn, since=m_start, until=m_end, expenses_only=True, net_display=True
                )
                month_rows.append((MONTHS_ES[m - 1], sum(g.total for g in groups)))
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
    finally:
        conn.close()

    # Barras por mes
    max_m = max((t for _, t in month_rows if t > 0), default=1)
    month_html_parts: list[str] = []
    for name, total in month_rows:
        if total <= 0:
            continue
        bar = min(100, max(3, int(round(total / max_m * 100))))
        month_html_parts.append(
            f"""
<tr>
  <td style="padding:8px 0 2px;font-size:14px;font-weight:600;color:#1c2833;">{name}</td>
  <td style="padding:8px 0 2px;text-align:right;font-size:14px;font-weight:700;
             color:#0e4d7b;">{_format_clp(total)}</td>
</tr>
<tr>
  <td colspan="2" style="padding:0 0 8px;">
    <div style="background:#eef2f6;border-radius:6px;height:10px;overflow:hidden;">
      <div style="width:{bar}%;background:#1a6fa8;height:10px;border-radius:6px;"></div>
    </div>
  </td>
</tr>"""
        )

    cat_block = _category_breakdown_html(
        all_groups,
        title="En qu&eacute; se ha gastado (todo el per&iacute;odo)",
        empty="Sin gasto de consumo en el per&iacute;odo",
    )
    since_l = since.strftime("%d/%m/%Y")
    until_l = until.strftime("%d/%m/%Y")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f0f3f7;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:480px;margin:0 auto;padding:24px 16px 40px;">

    <div style="background:linear-gradient(145deg,#0e4d7b 0%,#1a6fa8 100%);
                color:#fff;border-radius:16px;padding:22px;">
      <div style="font-size:13px;opacity:0.85;">Digest &middot; una sola vez</div>
      <div style="font-size:15px;margin-top:6px;opacity:0.95;">
        {since_l} &rarr; {until_l}
      </div>
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;
                  opacity:0.8;margin-top:18px;">Total gastado</div>
      <div style="font-size:32px;font-weight:700;letter-spacing:-0.02em;margin-top:4px;">
        {_format_clp(total_all)}
      </div>
      <div style="font-size:12px;opacity:0.8;margin-top:6px;">
        Consumo neto · sin transferencias ni pagos de tarjeta
      </div>
    </div>

    <div style="background:#fff;border-radius:14px;padding:18px 20px;margin-top:14px;
                box-shadow:0 1px 3px rgba(15,40,70,0.06);">
      <div style="font-size:13px;font-weight:700;color:#0e4d7b;margin-bottom:8px;
                  text-transform:uppercase;letter-spacing:0.04em;">Por mes</div>
      <table style="width:100%;border-collapse:collapse;">
        {''.join(month_html_parts) if month_html_parts else '<tr><td class="empty">Sin datos</td></tr>'}
      </table>
    </div>

    <div style="background:#fff;border-radius:14px;padding:18px 20px;margin-top:14px;
                box-shadow:0 1px 3px rgba(15,40,70,0.06);">
      {cat_block}
      <div style="margin-top:14px;padding-top:12px;border-top:1px solid #eef1f5;
                  font-size:13px;color:#5d6d7e;">
        Total per&iacute;odo
        <span style="float:right;font-size:18px;font-weight:700;color:#0e4d7b;">
          {_format_clp(total_all)}
        </span>
      </div>
    </div>

    <p style="text-align:center;color:#a0aab4;font-size:11px;margin:20px 0 0;">
      EconomicScript · digest hist&oacute;rico · no se repite autom&aacute;ticamente
    </p>
  </div>
</body>
</html>"""


def _smtp_send(subject: str, html_body: str) -> None:
    smtp_to = config.SMTP_TO
    if not smtp_to:
        LOGGER.warning("SMTP_TO no configurado — no se enviará el reporte.")
        return
    smtp_user = config.SMTP_USER or config.IMAP_USER
    smtp_password = config.SMTP_PASSWORD
    if not smtp_user or not smtp_password:
        LOGGER.error("Credenciales SMTP no disponibles.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = smtp_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [smtp_to], msg.as_string())
    LOGGER.info("Email enviado a %s — %s", smtp_to, subject)


def send_daily_report(
    report_date: date | None = None,
    partial: bool = False,
    slot_label: str | None = None,
) -> None:
    """Genera y envía el reporte diario por email vía SMTP (Gmail TLS)."""
    if report_date is None:
        report_date = date.today() if partial else date.today() - timedelta(days=1)

    html_body = _build_html_report(report_date, partial=partial)
    day_label = report_date.strftime("%d/%m/%Y")
    cycle_name = get_cycle_label(report_date)
    if slot_label:
        subject_suffix = f" — {slot_label}"
    elif partial:
        subject_suffix = " (hoy)"
    else:
        subject_suffix = ""

    subject = f"[EconomicScript] {day_label} · {cycle_name}{subject_suffix}"
    try:
        _smtp_send(subject, html_body)
        LOGGER.info("Reporte del %s enviado", day_label)
    except Exception as exc:
        LOGGER.error("Error al enviar reporte del %s: %s", day_label, exc)
        raise


def send_digest_report(
    *,
    since: date | None = None,
    until: date | None = None,
) -> None:
    """Envía un digest único (p. ej. desde enero del año en curso). No es periódico."""
    until = until or date.today()
    since = since or date(until.year, 1, 1)
    html = _build_digest_html(since=since, until=until)
    subject = (
        f"[EconomicScript] Digest {since.strftime('%b %Y')}–{until.strftime('%b %Y')} "
        f"· una sola vez"
    )
    _smtp_send(subject, html)
    LOGGER.info("Digest %s → %s enviado", since.isoformat(), until.isoformat())
