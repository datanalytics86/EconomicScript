"""Utilidades para normalización de datos financieros chilenos."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SANTIAGO_TZ = ZoneInfo("America/Santiago")
DATE_FORMATS = (
    "%d/%m/%Y %H:%M:%S",  # BancoEstado transferencia: 27/02/2026 12:06:28
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y",
    # Formato corto usado en EECC bancarios (ej: 30/01/26 → 30/01/2026)
    "%d/%m/%y",
    "%d-%m-%y",
    # ISO usado en alertas BCI "compra no habitual"
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def normalize_clp_amount(raw_amount: str) -> int:
    """Convierte montos CLP a entero. Preserva signo negativo para abonos.

    Maneja: "-1.234", "$ -1.234", "-$1.234", "$-1.234", "$1.234".
    """
    stripped = raw_amount.strip()
    # Detecta negativo en cualquier posición (ej EECC: "$ -4.446.270")
    negative = "-" in stripped
    digits_only = re.sub(r"[^0-9]", "", stripped)
    if not digits_only:
        raise ValueError(f"Monto inválido: {raw_amount!r}")
    value = int(digits_only)
    if value == 0:
        raise ValueError(f"Monto cero no permitido: {raw_amount!r}")
    return -value if negative else value


def parse_chilean_date(raw_date: str) -> datetime:
    """Parsea fechas DD/MM/YYYY, DD-MM-YYYY, o DD/MM/YY (año corto), con hora opcional."""

    stripped = raw_date.strip()
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(stripped, fmt)
            return parsed.replace(tzinfo=SANTIAGO_TZ)
        except ValueError:
            continue
    raise ValueError(
        f"Fecha inválida (formatos esperados DD/MM/YYYY o DD-MM-YYYY): {raw_date!r}"
    )


# Día de corte del ciclo de gasto (ej. 27 → ciclo 27/jul–26/ago = “Agosto”)
CYCLE_START_DAY: int = 27

MONTHS_ES: tuple[str, ...] = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


def get_cycle_start_date(today: date | None = None) -> date:
    """Inicio del ciclo de gasto: día 27 del mes en curso o del anterior.

    - Si hoy es 27 o posterior → ciclo desde el 27 de este mes.
    - Si hoy es 1–26 → ciclo desde el 27 del mes anterior.

    Ejemplo: 29/07 → 27/07; 10/08 → 27/07; 27/08 → 27/08.
    """
    if today is None:
        today = date.today()
    if today.day >= CYCLE_START_DAY:
        return today.replace(day=CYCLE_START_DAY)
    # Mes anterior, día 27
    first = today.replace(day=1)
    prev_month_last = first - timedelta(days=1)
    return prev_month_last.replace(day=CYCLE_START_DAY)


def get_cycle_label(today: date | None = None) -> str:
    """Nombre del mes del ciclo de facturación/gasto.

    El ciclo que empieza el 27 de un mes se etiqueta con el **mes siguiente**
    (ej. 27/jul–26/ago → “Agosto”). Así el “Total acumulado agosto” es legible.
    """
    start = get_cycle_start_date(today)
    if start.month == 12:
        return MONTHS_ES[0]  # Enero
    return MONTHS_ES[start.month]  # mes siguiente (0-index: month es 1-based)


def compute_content_hash(bank: str, date: str, amount: int, merchant: str) -> str:
    """Hash determinista SHA-256 (16 chars) para deduplicar transacciones de cartola."""

    payload = f"{bank}|{date}|{amount}|{merchant.strip().upper()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── Gasto de consumo neto ─────────────────────────────────────────────────────
# Política:
#   1. Anulaciones se parsean como type="Anulación TC" y amount < 0.
#   2. En totales de gasto real se SUMAN los amounts de tipos de consumo
#      (Compra TC + Anulación TC + …). El provisorio (+X) y su anulación (-X)
#      se cancelan; queda solo el cargo final.
#   3. Transferencias y pagos de tarjeta NO son gasto de consumo (movimiento
#      entre cuentas / pago de deuda ya gastada).
#
# Convención de signo:
#   amount > 0  → cargo / salida de dinero
#   amount < 0  → anulación / reverso / abono que reduce gasto

NON_CONSUMPTION_TYPES: frozenset[str] = frozenset(
    {
        "Transferencia",
        "Transferencia Propia",
        "Transferencia Entrante",
        "Transferencia Recibida",
        "Pago TC",
        "Pago Producto",
    }
)

# Prefijos de type que nunca entran al gasto de consumo
_NON_CONSUMPTION_PREFIXES: tuple[str, ...] = (
    "Transferencia",
    "Pago TC",
    "Pago Producto",
    "Pago ",  # Pago * genérico (no es compra)
)

# Categorías que nunca son "gasto de bolsillo" (aunque el type esté mal)
NON_CONSUMPTION_CATEGORIES: frozenset[str] = frozenset(
    {
        "Transferencias",
        "Pagos tarjeta",
        "Ingresos",
    }
)

# Fragmento SQL reutilizable (alias de tabla `t`) para filtros de consumo neto.
# Incluye Anulación TC / Compra TC (amount puede ser < 0) y excluye
# transferencias y pagos de tarjeta por type (y por categoría vía JOIN).
CONSUMPTION_SQL_FILTER: str = (
    "("
    "  t.type NOT LIKE 'Transferencia%'"
    "  AND t.type NOT LIKE 'Pago TC%'"
    "  AND t.type NOT LIKE 'Pago Producto%'"
    "  AND COALESCE(t.type, '') NOT IN ("
    "    'Transferencia','Transferencia Propia',"
    "    'Transferencia Entrante','Transferencia Recibida',"
    "    'Pago TC','Pago Producto'"
    "  )"
    ")"
)

# Exclusión por nombre de categoría (requiere LEFT JOIN categories c)
CONSUMPTION_CATEGORY_SQL_FILTER: str = (
    "("
    "  c.name IS NULL"
    "  OR c.name NOT IN ('Transferencias', 'Pagos tarjeta', 'Ingresos')"
    ")"
)


def is_consumption_type(tx_type: str | None) -> bool:
    """True si el tipo cuenta para gasto de consumo neto (incluye Anulación TC).

    Transferencias y pagos de tarjeta → False (no son gasto de consumo).
    """
    if not tx_type:
        return True
    if tx_type in NON_CONSUMPTION_TYPES:
        return False
    return not any(tx_type.startswith(p) for p in _NON_CONSUMPTION_PREFIXES)


def is_consumption_category(category: str | None) -> bool:
    """False para Transferencias / Pagos tarjeta / Ingresos."""
    if not category:
        return True
    return category.strip() not in NON_CONSUMPTION_CATEGORIES


def is_real_expense(
    tx_type: str | None,
    amount: int | None = None,
    category: str | None = None,
) -> bool:
    """Fila que entra al total de gasto real (consumo neto).

    - Incluye Anulación TC (amount < 0) para netear preauth.
    - Excluye transferencias, pagos TC y categorías no-consumo.
    """
    del amount
    if not is_consumption_type(tx_type):
        return False
    if not is_consumption_category(category):
        return False
    return True


def format_clp(amount: int) -> str:
    """Formatea CLP con signo y separador de miles chileno."""
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.0f}".replace(",", ".")
