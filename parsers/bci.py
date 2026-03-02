"""Parser de correos BCI."""

from __future__ import annotations

import re

from models import TransactionRecord
from parsers.base import BankParser
from utils import normalize_clp_amount, parse_chilean_date


class BCIParser(BankParser):
    """Extrae transacciones desde notificaciones BCI."""

    bank_name = "BCI"
    sender_patterns = ("@bci.cl",)
    transaction_pattern = re.compile(
        r"Tipo:\s*(?P<type>.+?)\s*\n"
        r"Monto:\s*\$?(?P<amount>[\d\.\-]+)\s*\n"
        r"Comercio:\s*(?P<merchant>.+?)\s*\n"
        r"Tarjeta:\s*(?P<card>.+?)\s*\n"
        r"Fecha:\s*(?P<date>[^\n]+)",
        re.IGNORECASE | re.DOTALL,
    )

    def can_parse(self, sender: str, subject: str, body: str) -> bool:
        return any(pattern in sender.lower() for pattern in self.sender_patterns) and (
            "notificación" in subject.lower() or "transacción" in body.lower()
        )

    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        match = self.transaction_pattern.search(body)
        if not match:
            raise ValueError("No fue posible parsear correo BCI")

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
