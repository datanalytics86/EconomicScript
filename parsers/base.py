"""Clases base para parseo de notificaciones bancarias."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Pattern

from models import TransactionRecord


class BankParser(ABC):
    """Contrato base para extraer transacciones desde texto de correos por banco."""

    bank_name: str
    sender_patterns: tuple[str, ...]
    transaction_pattern: Pattern[str]

    @abstractmethod
    def can_parse(self, sender: str, subject: str, body: str) -> bool:
        """Determina si el parser aplica para el correo recibido."""

    @abstractmethod
    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        """Parsea el cuerpo de correo y retorna una transacción normalizada."""
