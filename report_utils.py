"""Utilidades compartidas para reportes agrupados por categoría."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import config
from utils import NON_CONSUMPTION_TYPES

UNCATEGORIZED_LABEL = "Sin categoría"


@dataclass
class CategoryGroup:
    category: str
    total: int
    transactions: list[sqlite3.Row]


def _format_clp(amount: int) -> str:
    return f"${abs(amount):,.0f}".replace(",", ".")


def fetch_transactions_grouped(
    conn: sqlite3.Connection,
    *,
    since: date | None = None,
    until: date | None = None,
    expenses_only: bool = True,
    consumption_only: bool = True,
    dedupe_sources: bool = True,
) -> list[CategoryGroup]:
    """Obtiene transacciones agrupadas por categoría, ordenadas por total descendente.

    Args:
        consumption_only: Si True, excluye transferencias y pagos de tarjeta.
        dedupe_sources: Si True, evita doble conteo gmail+cartola prefiriendo gmail
            (cartola solo si no está verificada / reconciliada).
    """
    filters: list[str] = []
    params: list[str] = []

    if since is not None:
        filters.append("DATE(t.date) >= ?")
        params.append(since.isoformat())
    if until is not None:
        filters.append("DATE(t.date) <= ?")
        params.append(until.isoformat())
    if expenses_only:
        filters.append("t.amount > 0")
    if consumption_only:
        placeholders = ", ".join("?" for _ in NON_CONSUMPTION_TYPES)
        filters.append(f"(t.type IS NULL OR t.type NOT IN ({placeholders}))")
        params.extend(sorted(NON_CONSUMPTION_TYPES))
    if dedupe_sources:
        filters.append(
            "(t.source = 'gmail' OR (t.source = 'cartola' AND COALESCE(t.verified, 0) = 0))"
        )

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    rows = conn.execute(
        f"""
        SELECT t.id, t.bank, t.merchant, t.type, t.amount, t.date,
               COALESCE(c.name, '{UNCATEGORIZED_LABEL}') AS category
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        {where}
        ORDER BY category, t.date DESC, t.amount DESC
        """,
        params,
    ).fetchall()

    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)

    result = [
        CategoryGroup(
            category=cat,
            total=sum(r["amount"] for r in txs),
            transactions=txs,
        )
        for cat, txs in grouped.items()
    ]
    result.sort(key=lambda g: g.total, reverse=True)
    return result


def fetch_uncategorized_expenses(
    conn: sqlite3.Connection,
    *,
    since: date | None = None,
    until: date | None = None,
    consumption_only: bool = True,
    dedupe_sources: bool = True,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """Gastos de consumo sin categoría (residual para triage diario)."""
    filters: list[str] = ["t.amount > 0", "t.category_id IS NULL"]
    params: list[str | int] = []

    if since is not None:
        filters.append("DATE(t.date) >= ?")
        params.append(since.isoformat())
    if until is not None:
        filters.append("DATE(t.date) <= ?")
        params.append(until.isoformat())
    if consumption_only:
        placeholders = ", ".join("?" for _ in NON_CONSUMPTION_TYPES)
        filters.append(f"(t.type IS NULL OR t.type NOT IN ({placeholders}))")
        params.extend(sorted(NON_CONSUMPTION_TYPES))
    if dedupe_sources:
        filters.append(
            "(t.source = 'gmail' OR (t.source = 'cartola' AND COALESCE(t.verified, 0) = 0))"
        )

    where = "WHERE " + " AND ".join(filters)
    return conn.execute(
        f"""
        SELECT t.id, t.bank, t.merchant, t.type, t.amount, t.date, t.source
        FROM transactions t
        {where}
        ORDER BY t.amount DESC, t.date DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()


def build_uncategorized_html(
    rows: list[sqlite3.Row],
    *,
    title: str,
    dashboard_url: str | None = None,
    empty_message: str = "Todas las compras del d\u00eda est\u00e1n categorizadas \u2705",
) -> str:
    """HTML del residual de categorización para el reporte diario."""
    if not rows:
        return f"""
  <h3>{title}</h3>
  <p class="empty">{empty_message}</p>"""

    rows_html = "\n".join(
        f"<tr>"
        f"<td>{r['date'][8:10]}/{r['date'][5:7]} {r['date'][11:16]}</td>"
        f"<td>{r['bank']}</td>"
        f"<td>{r['merchant'] or '—'}</td>"
        f"<td>{r['type'] or ''}</td>"
        f"<td class='num'>{_format_clp(r['amount'])}</td>"
        f"</tr>"
        for r in rows
    )
    total = sum(int(r["amount"]) for r in rows)
    link_html = ""
    if dashboard_url:
        sep = "&" if "?" in dashboard_url else "?"
        href = f"{dashboard_url}{sep}view=categorizar"
        link_html = (
            f"<p style='margin-top:12px;'>"
            f"<a href='{href}' style='color:#1a5276;font-weight:bold;'>"
            f"Abrir dashboard para categorizar (aprende la regla del comercio)"
            f"</a></p>"
        )
    else:
        link_html = (
            "<p style='margin-top:12px;color:#555;font-size:0.95em;'>"
            "Abre el dashboard Streamlit &rarr; <b>Categorizar y recategorizar</b>. "
            "Al guardar una vez, el comercio queda aprendido para la pr&oacute;xima."
            "</p>"
        )

    return f"""
  <h3>{title}</h3>
  <p style="background:#fff8e6;border-left:4px solid #e67e22;padding:10px 12px;border-radius:4px;">
    <b>{len(rows)} movimiento(s)</b> de consumo sin categor&iacute;a
    (total {_format_clp(total)}). Categoriza una vez por comercio y la regla se reutiliza.
  </p>
  <table>
    <tr><th>Fecha</th><th>Banco</th><th>Comercio</th><th>Tipo</th><th>Monto</th></tr>
    {rows_html}
  </table>
  {link_html}"""


def build_category_groups_html(
    groups: list[CategoryGroup],
    *,
    title: str,
    empty_message: str = "Sin transacciones registradas",
) -> str:
    """Genera HTML con cada categoría como sección y todas sus transacciones."""
    if not groups:
        return f"<p class='empty'>{empty_message}</p>"

    sections: list[str] = []
    grand_total = sum(g.total for g in groups)

    for group in groups:
        rows_html = "\n".join(
            f"<tr>"
            f"<td>{r['date'][8:10]}/{r['date'][5:7]} {r['date'][11:16]}</td>"
            f"<td>{r['bank']}</td>"
            f"<td>{r['merchant']}</td>"
            f"<td>{r['type'] or ''}</td>"
            f"<td class='num'>{_format_clp(r['amount'])}</td>"
            f"</tr>"
            for r in group.transactions
        )
        sections.append(
            f"""
  <div class="cat-block">
    <h4>{group.category} &mdash; {_format_clp(group.total)} ({len(group.transactions)} mov.)</h4>
    <table>
      <tr><th>Fecha</th><th>Banco</th><th>Comercio</th><th>Tipo</th><th>Monto</th></tr>
      {rows_html}
      <tr class="subtotal-row">
        <td colspan="4"><b>Subtotal {group.category}</b></td>
        <td class="num"><b>{_format_clp(group.total)}</b></td>
      </tr>
    </table>
  </div>"""
        )

    summary_rows = "\n".join(
        f"<tr><td>{g.category}</td>"
        f"<td class='num'>{len(g.transactions)}</td>"
        f"<td class='num'>{_format_clp(g.total)}</td>"
        f"<td class='num'>{g.total / grand_total * 100:.1f}%</td></tr>"
        for g in groups
    )

    return f"""
  <h3>{title}</h3>
  <table class="summary-table">
    <tr><th>Categor&iacute;a</th><th># Mov.</th><th>Total</th><th>%</th></tr>
    {summary_rows}
    <tr class="total-row">
      <td><b>Total</b></td>
      <td class="num"><b>{sum(len(g.transactions) for g in groups)}</b></td>
      <td class="num"><b>{_format_clp(grand_total)}</b></td>
      <td class="num"><b>100%</b></td>
    </tr>
  </table>
  {''.join(sections)}"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn