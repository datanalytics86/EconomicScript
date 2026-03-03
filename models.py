"""Modelos de dominio para transacciones financieras."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

_VALID_BANKS = frozenset({"BCI", "BANCO_ESTADO", "SECURITY"})
_VALID_SOURCES = frozenset({"gmail", "cartola"})


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
    content_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if self.bank not in _VALID_BANKS:
            raise ValueError(f"Banco inválido: {self.bank!r}. Permitidos: {_VALID_BANKS}")
        if self.source not in _VALID_SOURCES:
            raise ValueError(f"Fuente inválida: {self.source!r}. Permitidas: {_VALID_SOURCES}")
        if self.amount == 0:
            raise ValueError("El monto no puede ser cero")
