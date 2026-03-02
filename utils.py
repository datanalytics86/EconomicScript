"""Utilidades para normalización de datos financieros chilenos."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

SANTIAGO_TZ = ZoneInfo("America/Santiago")
DATE_FORMATS = ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y")


def normalize_clp_amount(raw_amount: str) -> int:
    """Convierte montos en formato CLP a entero, eliminando símbolos y separadores."""

    sanitized = re.sub(r"[^0-9-]", "", raw_amount.replace(".", ""))
    if not sanitized:
        raise ValueError(f"Monto inválido: {raw_amount}")
    return int(sanitized)


def parse_chilean_date(raw_date: str) -> datetime:
    """Parsea fechas chilenas DD/MM/YYYY o DD-MM-YYYY, opcionalmente con hora."""

    stripped = raw_date.strip()
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(stripped, fmt)
            return parsed.replace(tzinfo=SANTIAGO_TZ)
        except ValueError:
            continue
    raise ValueError(f"Fecha inválida: {raw_date}")
