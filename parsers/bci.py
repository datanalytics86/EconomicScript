"""Parser de correos BCI.

Soporta dos tipos de notificación:
  - Compra con tarjeta de crédito (from: contacto@bci.cl)
  - Aviso de transferencia de fondos (from: transferencias@bci.cl)

Formato real observado en muestras:
  TC:          Monto $202.502 / Fecha 02/03/2026 / Comercio XXXXX
  Transferencia: Monto transferido $100.000 / Nombre del destinatario XXX / Fecha de abono 01/03/2026
"""

from __future__ import annotations

import re

from models import TransactionRecord
from parsers.base import BankParser
from utils import normalize_clp_amount, parse_chilean_date


class BCIParser(BankParser):
    """Extrae transacciones desde notificaciones BCI (TC y transferencias)."""

    bank_name = "BCI"
    sender_patterns = ("@bci.cl",)

    # Aviso de transferencia de fondos
    # Campos: Monto transferido / Nombre del destinatario / Fecha de abono
    _PATTERN_TRANSFER = re.compile(
        r"Monto transferido\s*:?\s*\$?(?P<amount>[\d\.]+).*?"
        r"Nombre del destinatario\s*:?\s*(?P<merchant>[^\n]+).*?"
        r"Fecha de abono\s*:?\s*(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Notificación de compra con tarjeta de crédito
    # Campos: Monto / Fecha / Comercio
    _PATTERN_TC = re.compile(
        r"Monto\s*:?\s*\$?(?P<amount>[\d\.]+).*?"
        r"Fecha\s*:?\s*(?P<date>\d{2}/\d{2}/\d{4}).*?"
        r"Comercio\s*:?\s*(?P<merchant>[^\n]+)",
        re.IGNORECASE | re.DOTALL,
    )

    def can_parse(self, sender: str, subject: str, body: str) -> bool:
        if not any(p in sender.lower() for p in self.sender_patterns):
            return False
        subject_l = subject.lower()
        body_l = body.lower()
        return (
            "notificación" in subject_l
            or "aviso de transferencia" in subject_l
            or "transacción" in body_l
            or "transferencia de fondos" in body_l
        )

    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        # Transferencia tiene prioridad (patrón más específico)
        match = self._PATTERN_TRANSFER.search(body)
        if match:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(match.group("date")),
                amount=normalize_clp_amount(match.group("amount")),
                type="Transferencia",
                merchant=match.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        match = self._PATTERN_TC.search(body)
        if match:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(match.group("date")),
                amount=normalize_clp_amount(match.group("amount")),
                type="Compra TC",
                merchant=match.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        raise ValueError("No fue posible parsear correo BCI")
