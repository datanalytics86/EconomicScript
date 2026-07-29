"""Utilidades compartidas para reportes: neteo, agrupación y HTML del email."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import config
from utils import (
    CONSUMPTION_CATEGORY_SQL_FILTER,
    CONSUMPTION_SQL_FILTER,
    format_clp,
    is_consumption_category,
    is_consumption_type,
)

UNCATEGORIZED_LABEL = "Sin categoría"
# Categoría solo de voids: no se muestra; el neto va al comercio de la compra
_VOID_CATEGORY = "Ajustes/Anulaciones"


@dataclass
class NetLine:
    """Línea de gasto ya neteada (sin anulación visible)."""

    merchant: str
    bank: str
    category: str
    amount: int
    date: str  # ISO o display
    n_ops: int = 1
    note: str = ""


@dataclass
class CategoryGroup:
    category: str
    total: int
    transactions: list  # rows crudos (legacy) o NetLine
    lines: list[NetLine] = field(default_factory=list)


def _format_clp(amount: int) -> str:
    return format_clp(amount)


def _norm_merchant(merchant: str | None) -> str:
    return re.sub(r"\s+", " ", (merchant or "").strip().upper())


def _is_void_type(tx_type: str | None) -> bool:
    t = (tx_type or "").lower()
    return "anulaci" in t or "reverso" in t


def fetch_raw_consumption(
    conn: sqlite3.Connection,
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[sqlite3.Row]:
    """Filas de consumo real (incluye Anulación TC negativa) en el rango.

    Excluye transferencias y pagos de tarjeta por **type** y por **categoría**
    (Transferencias / Pagos tarjeta / Ingresos no son gasto).
    """
    filters: list[str] = [
        f"({CONSUMPTION_SQL_FILTER})",
        f"({CONSUMPTION_CATEGORY_SQL_FILTER})",
    ]
    params: list[str] = []
    if since is not None:
        filters.append("DATE(t.date) >= ?")
        params.append(since.isoformat())
    if until is not None:
        filters.append("DATE(t.date) <= ?")
        params.append(until.isoformat())
    where = "WHERE " + " AND ".join(filters)
    return conn.execute(
        f"""
        SELECT t.id, t.bank, t.merchant, t.type, t.amount, t.date,
               COALESCE(c.name, '{UNCATEGORIZED_LABEL}') AS category
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        {where}
        ORDER BY t.date DESC, t.amount DESC
        """,
        params,
    ).fetchall()


def net_lines_from_rows(rows: list) -> list[NetLine]:
    """Agrupa por comercio y suma montos: preauth + anulación se cancelan.

    - No se listan anulaciones por separado.
    - Ejemplo: +1000 y −990 → una línea neta de +10.
    - Uber +8000 +8190 −8000 → una línea de +8190.
    - Líneas con neto 0 se ocultan.
    - Transferencias / pagos TC se ignoran (no son gasto).
    - Categoría = la de la compra (no Ajustes/Anulaciones).
    """
    # key → aggregates
    buckets: dict[str, dict] = {}

    for r in rows:
        merchant = (r["merchant"] if hasattr(r, "keys") else r.get("merchant")) or "—"
        bank = (r["bank"] if hasattr(r, "keys") else r.get("bank")) or ""
        amount = int(r["amount"] if hasattr(r, "keys") else r["amount"])
        cat = (r["category"] if hasattr(r, "keys") else r.get("category")) or UNCATEGORIZED_LABEL
        tx_type = r["type"] if hasattr(r, "keys") else r.get("type")
        dt = r["date"] if hasattr(r, "keys") else r.get("date")

        # Defensa en profundidad: nunca tratar transferencias/pagos como gasto
        if not is_consumption_type(tx_type):
            continue
        if not is_consumption_category(cat):
            continue

        key = _norm_merchant(merchant)

        if key not in buckets:
            buckets[key] = {
                "merchant": merchant.strip() or "—",
                "bank": bank,
                "amount": 0,
                "n_ops": 0,
                "n_voids": 0,
                "date": str(dt or ""),
                "cat_votes": defaultdict(int),  # category → sum of positive amounts
            }
        b = buckets[key]
        b["amount"] += amount
        b["n_ops"] += 1
        if _is_void_type(tx_type) or amount < 0:
            b["n_voids"] += 1
        else:
            # Prefer category of real purchases
            if cat != _VOID_CATEGORY:
                b["cat_votes"][cat] += max(amount, 0)
        # Keep most recent date string
        if str(dt or "") > b["date"]:
            b["date"] = str(dt or "")
        if bank and not b["bank"]:
            b["bank"] = bank

    lines: list[NetLine] = []
    for b in buckets.values():
        net = int(b["amount"])
        if net == 0:
            continue  # preauth + void fully cancelled, hide
        # Category: best positive vote, else first non-void, else Sin categoría
        if b["cat_votes"]:
            category = max(b["cat_votes"].items(), key=lambda x: x[1])[0]
        else:
            category = UNCATEGORIZED_LABEL
        note = ""
        if b["n_voids"] and b["n_ops"] > 1:
            note = "neto (preauth/anul. aplicadas)"
        lines.append(
            NetLine(
                merchant=b["merchant"],
                bank=b["bank"],
                category=category,
                amount=net,
                date=b["date"],
                n_ops=b["n_ops"],
                note=note,
            )
        )

    lines.sort(key=lambda x: x.amount, reverse=True)
    return lines


def group_net_lines(lines: list[NetLine]) -> list[CategoryGroup]:
    """Agrupa líneas netas por categoría (sin Ajustes ni Transferencias/Pagos)."""
    by_cat: dict[str, list[NetLine]] = defaultdict(list)
    for line in lines:
        cat = line.category if line.category != _VOID_CATEGORY else UNCATEGORIZED_LABEL
        if not is_consumption_category(cat):
            continue  # Transferencias / Pagos tarjeta / Ingresos fuera del gasto
        by_cat[cat].append(line)

    result: list[CategoryGroup] = []
    for cat, cat_lines in by_cat.items():
        cat_lines.sort(key=lambda x: x.amount, reverse=True)
        total = sum(L.amount for L in cat_lines)
        if total == 0 and not cat_lines:
            continue
        result.append(
            CategoryGroup(
                category=cat,
                total=total,
                transactions=cat_lines,  # type: ignore[arg-type]
                lines=cat_lines,
            )
        )
    result.sort(key=lambda g: g.total, reverse=True)
    return result


def fetch_transactions_grouped(
    conn: sqlite3.Connection,
    *,
    since: date | None = None,
    until: date | None = None,
    expenses_only: bool = True,
    net_display: bool = True,
) -> list[CategoryGroup]:
    """Obtiene gastos de consumo agrupados.

    net_display=True (default para email): agrupa por comercio y oculta anulaciones;
    el total es el neto (ej. 1000−990=10).
    """
    if not expenses_only:
        # Modo legacy: todas las filas por categoría cruda
        filters: list[str] = []
        params: list[str] = []
        if since is not None:
            filters.append("DATE(t.date) >= ?")
            params.append(since.isoformat())
        if until is not None:
            filters.append("DATE(t.date) <= ?")
            params.append(until.isoformat())
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
        grouped: dict[str, list] = defaultdict(list)
        for row in rows:
            grouped[row["category"]].append(row)
        result = [
            CategoryGroup(
                category=cat,
                total=sum(r["amount"] for r in txs),
                transactions=txs,
                lines=[],
            )
            for cat, txs in grouped.items()
        ]
        result.sort(key=lambda g: g.total, reverse=True)
        return result

    rows = fetch_raw_consumption(conn, since=since, until=until)
    if net_display:
        lines = net_lines_from_rows(rows)
        return group_net_lines(lines)

    # Sin net_display: filas crudas por categoría (incluye anulaciones)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)
    result = [
        CategoryGroup(
            category=cat,
            total=sum(r["amount"] for r in txs),
            transactions=txs,
            lines=[],
        )
        for cat, txs in grouped.items()
    ]
    result.sort(key=lambda g: g.total, reverse=True)
    return result


def _bar_row(label: str, amount: int, max_amount: int, color: str = "#1a5276") -> str:
    """Fila de barra horizontal CSS-only (compatible con clientes de email)."""
    pct = 0 if max_amount <= 0 else min(100, int(round(abs(amount) / max_amount * 100)))
    if pct < 2 and amount != 0:
        pct = 2
    bar_color = "#c0392b" if amount < 0 else color
    return f"""
    <tr>
      <td style="padding:6px 8px;width:38%;font-size:13px;color:#333;">{label}</td>
      <td style="padding:6px 4px;width:42%;">
        <div style="background:#eef2f6;border-radius:6px;height:14px;overflow:hidden;">
          <div style="width:{pct}%;background:{bar_color};height:14px;border-radius:6px;"></div>
        </div>
      </td>
      <td style="padding:6px 8px;text-align:right;font-size:13px;font-weight:600;
                 white-space:nowrap;color:#1a5276;">{_format_clp(amount)}</td>
    </tr>"""


def build_category_bars_html(
    groups: list[CategoryGroup],
    *,
    title: str = "Distribuci&oacute;n por categor&iacute;a",
) -> str:
    """Gráfico de barras horizontales por categoría (neto)."""
    positives = [g for g in groups if g.total > 0]
    if not positives:
        return f"<p class='empty'>Sin datos para {title}</p>"
    max_amt = max(g.total for g in positives)
    rows = "\n".join(
        _bar_row(g.category, g.total, max_amt) for g in positives[:12]
    )
    return f"""
  <div class="card">
    <h3 style="margin-top:0;">{title}</h3>
    <table style="width:100%;border-collapse:collapse;">{rows}</table>
  </div>"""


def build_daily_bars_html(
    day_totals: list[tuple[date, int]],
    *,
    title: str = "Gasto diario (neto)",
) -> str:
    """Barras de los últimos N días (más reciente primero o cronológico)."""
    if not day_totals:
        return ""
    # Orden cronológico para lectura izquierda→derecha visual en lista
    ordered = sorted(day_totals, key=lambda x: x[0])
    max_amt = max((a for _, a in ordered if a > 0), default=1)
    rows = "\n".join(
        _bar_row(d.strftime("%d/%m"), total, max_amt, color="#2874a6")
        for d, total in ordered
    )
    return f"""
  <div class="card">
    <h3 style="margin-top:0;">{title}</h3>
    <table style="width:100%;border-collapse:collapse;">{rows}</table>
  </div>"""


def build_category_groups_html(
    groups: list[CategoryGroup],
    *,
    title: str,
    empty_message: str = "Sin transacciones registradas",
    show_detail: bool = True,
) -> str:
    """HTML de categorías con líneas netas (sin anulaciones sueltas)."""
    if not groups:
        return f"<p class='empty'>{empty_message}</p>"

    grand_total = sum(g.total for g in groups)
    # Solo positivos en % del pie (negativos residuales raros)
    pos_total = sum(g.total for g in groups if g.total > 0) or 1

    summary_rows = "\n".join(
        f"<tr>"
        f"<td>{g.category}</td>"
        f"<td class='num'>{len(g.lines) if g.lines else len(g.transactions)}</td>"
        f"<td class='num'>{_format_clp(g.total)}</td>"
        f"<td class='num'>{(g.total / pos_total * 100) if g.total > 0 else 0:.1f}%</td>"
        f"</tr>"
        for g in groups
        if g.total != 0
    )

    sections: list[str] = []
    if show_detail:
        for group in groups:
            if group.total == 0:
                continue
            lines = group.lines or []
            if lines:
                rows_html = "\n".join(
                    f"<tr>"
                    f"<td>{_short_date(L.date)}</td>"
                    f"<td>{L.bank}</td>"
                    f"<td>{_escape(L.merchant)}"
                    f"{' <span class=\"hint\">· ' + L.note + '</span>' if L.note else ''}"
                    f"</td>"
                    f"<td class='num muted'>{L.n_ops} op.</td>"
                    f"<td class='num'><b>{_format_clp(L.amount)}</b></td>"
                    f"</tr>"
                    for L in lines
                    if L.amount != 0
                )
            else:
                # Fallback filas crudas (sin net)
                rows_html = "\n".join(
                    f"<tr>"
                    f"<td>{_short_date(r['date'])}</td>"
                    f"<td>{r['bank']}</td>"
                    f"<td>{_escape(r['merchant'] or '')}</td>"
                    f"<td class='num muted'>{r['type'] or ''}</td>"
                    f"<td class='num'>{_format_clp(r['amount'])}</td>"
                    f"</tr>"
                    for r in group.transactions
                )
            n_lines = len(lines) if lines else len(group.transactions)
            sections.append(
                f"""
  <div class="cat-block">
    <h4>{group.category} &mdash; {_format_clp(group.total)}
      <span class="hint">({n_lines} comercio{'s' if n_lines != 1 else ''})</span></h4>
    <table>
      <tr><th>Fecha</th><th>Banco</th><th>Comercio</th><th></th><th>Neto</th></tr>
      {rows_html}
      <tr class="subtotal-row">
        <td colspan="4"><b>Subtotal {group.category}</b></td>
        <td class="num"><b>{_format_clp(group.total)}</b></td>
      </tr>
    </table>
  </div>"""
            )

    return f"""
  <div class="card">
  <h3 style="margin-top:0;">{title}</h3>
  <table class="summary-table">
    <tr><th>Categor&iacute;a</th><th>#</th><th>Total neto</th><th>%</th></tr>
    {summary_rows}
    <tr class="total-row">
      <td><b>Total</b></td>
      <td class="num"><b>{sum(len(g.lines) if g.lines else len(g.transactions) for g in groups)}</b></td>
      <td class="num"><b>{_format_clp(grand_total)}</b></td>
      <td class="num"><b>100%</b></td>
    </tr>
  </table>
  </div>
  {''.join(sections) if show_detail else ''}"""


def _short_date(raw: str) -> str:
    """'2026-07-29 00:00:00' → '29/07'."""
    s = str(raw or "")
    if len(s) >= 10 and s[4] == "-":
        return f"{s[8:10]}/{s[5:7]}"
    return s[:10]


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
