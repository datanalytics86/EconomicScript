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


def get_cycle_start_date(today: date | None = None) -> date:
    """Retorna el 2do-último día hábil del mes anterior como inicio del ciclo de gasto.

    Los días hábiles excluyen fines de semana y feriados legales chilenos.
    El ciclo se resetea en ese día, alineándose con el corte de tarjetas de crédito.
    """
    import holidays as holidays_lib  # importación diferida para no requerir en tests básicos

    if today is None:
        today = date.today()

    first_of_current = today.replace(day=1)
    last_of_prev = first_of_current - timedelta(days=1)
    cl_holidays = holidays_lib.CL(years=last_of_prev.year)

    business_days = 0
    current = last_of_prev
    while current.month == last_of_prev.month:
        if current.weekday() < 5 and current not in cl_holidays:
            business_days += 1
            if business_days == 2:
                return current
        current -= timedelta(days=1)

    # Fallback improbable: si el mes anterior tuviera < 2 días hábiles
    return last_of_prev.replace(day=1)


def compute_content_hash(bank: str, date: str, amount: int, merchant: str) -> str:
    """Hash determinista SHA-256 (16 chars) para deduplicar transacciones de cartola."""

    payload = f"{bank}|{date}|{amount}|{merchant.strip().upper()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
