"""Parser de correos Banco Security.

Formatos reales observados en muestras:

  Compra TC (notificaciones@security.cl):
    "El DD/MM/YYYY a las HH:MM realizaste una compra en MERCHANT CHL de $MONTO
     con cargo a la tarjeta ***XXXX."

  Transferencia saliente (noresponder@bancosecurity.cl):
    campo-por-línea separado por dos puntos → valor en línea siguiente:
    Monto:\n$ 2.500.000\n...\nFecha y hora:\n02/03/2026 16:00 hrs.\n...\nNombre:\nNicolas Andrade

  Transferencia entrante (notificaciones@security.cl):
    "El DD/MM/YYYY a las HH:MM recibiste una TRANSFERENCIA DESDE BANCO DE NOMBRE
     en la cuenta ***XXXX de $MONTO."
"""

from __future__ import annotations

import re

from models import TransactionRecord
from parsers.base import BankParser
from utils import normalize_clp_amount, parse_chilean_date


class SecurityParser(BankParser):
    """Parser de notificaciones Banco Security (compras TC y transferencias)."""

    bank_name = "SECURITY"
    sender_patterns = ("@security.cl", "@bancosecurity.cl")

    # Compra TC: "El DD/MM/YYYY a las HH:MM realizaste una compra en MERCHANT de $MONTO"
    _PATTERN_COMPRA = re.compile(
        r"El\s+(?P<date>\d{2}/\d{2}/\d{4})\s+a\s+las\s+\d+:\d+"
        r"\s+realizaste\s+una\s+compra\s+en\s+(?P<merchant>.+?)"
        r"\s+de\s+\$(?P<amount>[\d\.]+)",
        re.IGNORECASE | re.DOTALL,
    )

    # Transferencia saliente: Monto: → valor → Fecha y hora: → valor → Nombre: → valor
    _PATTERN_TRANSFER_OUT = re.compile(
        r"Monto:\s*[\n\r\s]*\$?\s*(?P<amount>[\d\.]+).*?"
        r"Fecha\s+y\s+hora:\s*[\n\r\s]*(?P<date>\d{2}/\d{2}/\d{4}).*?"
        r"Nombre:\s*[\n\r\s]*(?P<merchant>[^\n\r]+)",
        re.IGNORECASE | re.DOTALL,
    )

    # Transferencia entrante: "recibiste una TRANSFERENCIA DESDE BANCO DE NOMBRE en cuenta ... de $X"
    _PATTERN_TRANSFER_IN = re.compile(
        r"El\s+(?P<date>\d{2}/\d{2}/\d{4}).*?"
        r"recibiste\s+una\s+TRANSFERENCIA\s+DESDE\s+\S+\s+DE\s+(?P<merchant>.+?)"
        r"\s+en\s+la\s+cuenta\s+\S+\s+de\s+\$(?P<amount>[\d\.]+)",
        re.IGNORECASE | re.DOTALL,
    )

    # Fallback legado: etiqueta:\nvalor (formato anterior)
    _PATTERN_LEGACY = re.compile(
        r"(?:Movimiento|Tipo):\s*(?P<type>.+?)\s*[\n\r]"
        r"(?:Monto|Total):\s*\$?(?P<amount>[\d\.\-]+)\s*[\n\r]"
        r"(?:Comercio|Detalle):\s*(?P<merchant>.+?)\s*[\n\r]"
        r"(?:Fecha|Fecha\s+y\s+hora):\s*(?P<date>[^\n\r]+)",
        re.IGNORECASE | re.DOTALL,
    )

    def can_parse(self, sender: str, subject: str, body: str) -> bool:
        return any(p in sender.lower() for p in self.sender_patterns)

    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        # 1. Compra TC
        m = self._PATTERN_COMPRA.search(body)
        if m:
            # Limpia código de país al final del merchant ("CHL", "CL", etc.)
            merchant = re.sub(r"\s+[A-Z]{2,3}\s*$", "", m.group("merchant")).strip()
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type="Compra TC",
                merchant=merchant or m.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 2. Transferencia saliente
        m = self._PATTERN_TRANSFER_OUT.search(body)
        if m:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type="Transferencia",
                merchant=m.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 3. Transferencia entrante
        m = self._PATTERN_TRANSFER_IN.search(body)
        if m:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type="Transferencia Recibida",
                merchant=m.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 4. Formato legado (etiqueta: valor)
        m = self._PATTERN_LEGACY.search(body)
        if m:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type=m.group("type").strip(),
                merchant=m.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        raise ValueError("No fue posible parsear correo Security")
