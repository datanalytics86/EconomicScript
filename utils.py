"""Utilidades para normalización de datos financieros chilenos."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo

SANTIAGO_TZ = ZoneInfo("America/Santiago")
DATE_FORMATS = ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y")


def normalize_clp_amount(raw_amount: str) -> int:
    """Convierte montos CLP a entero. Preserva signo negativo para abonos."""

    stripped = raw_amount.strip()
    negative = stripped.startswith("-")
    # Extrae solo dígitos (elimina puntos separadores de miles, $, espacios)
    digits_only = re.sub(r"[^0-9]", "", stripped.replace(".", "").replace(",", ""))
    if not digits_only:
        raise ValueError(f"Monto inválido: {raw_amount!r}")
    value = int(digits_only)
    if value == 0:
        raise ValueError(f"Monto cero no permitido: {raw_amount!r}")
    return -value if negative else value


def parse_chilean_date(raw_date: str) -> datetime:
    """Parsea fechas DD/MM/YYYY o DD-MM-YYYY, opcionalmente con hora HH:MM."""

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


def compute_content_hash(bank: str, date: str, amount: int, merchant: str) -> str:
    """Hash determinista SHA-256 (16 chars) para deduplicar transacciones de cartola."""

    payload = f"{bank}|{date}|{amount}|{merchant.strip().upper()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
