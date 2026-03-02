"""Parser de correos Banco Estado.

Incluye implementación base utilizable y extensible cuando se integren
formatos reales sanitizados.
"""

from __future__ import annotations

import re

from models import TransactionRecord
from parsers.base import BankParser
from utils import normalize_clp_amount, parse_chilean_date


class BancoEstadoParser(BankParser):
    """Parser inicial de correos Banco Estado (plantilla funcional)."""

    bank_name = "BANCO_ESTADO"
    sender_patterns = ("@bancoestado.cl",)
    transaction_pattern = re.compile(
        r"(?:Tipo|Glosa):\s*(?P<type>.+?)\s*\n"
        r"(?:Monto|Importe):\s*\$?(?P<amount>[\d\.\-]+)\s*\n"
        r"(?:Comercio|Descripción):\s*(?P<merchant>.+?)\s*\n"
        r"(?:Fecha|Fecha operación):\s*(?P<date>[^\n]+)",
        re.IGNORECASE | re.DOTALL,
    )

    def can_parse(self, sender: str, subject: str, body: str) -> bool:
        return any(pattern in sender.lower() for pattern in self.sender_patterns)

    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        match = self.transaction_pattern.search(body)
        if not match:
            raise ValueError("No fue posible parsear correo Banco Estado")

        return TransactionRecord(
            bank=self.bank_name,
            date=parse_chilean_date(match.group("date")),
            amount=normalize_clp_amount(match.group("amount")),
            type=match.group("type").strip(),
            merchant=match.group("merchant").strip(),
            source="gmail",
            raw_text=body,
            gmail_message_id=gmail_message_id,
        )
