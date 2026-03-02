"""Modelos de dominio para transacciones financieras."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class TransactionRecord:
    """Representa una transacción normalizada para persistencia."""

    bank: str
    date: datetime
    amount: int
    type: str
    merchant: str
    source: str
    raw_text: str
    gmail_message_id: Optional[str] = None
    statement_ref: Optional[str] = None
