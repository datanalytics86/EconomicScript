"""Parser de correos Banco Estado.

Formatos reales observados en muestras:

  Compra TC (notificaciones@correo.bancoestado.cl):
    "Se ha realizado una compra por $ 2.990 en MERPAGO*MELIMAS asociado a su
     tarjeta de crédito terminada en **** 0608 el día 27/02/2026 a las 15:12 hrs."

  Transferencia saliente (noreply@correo.bancoestado.cl):
    campo-por-línea: etiqueta en una línea, valor en la siguiente
    Monto\n$1.200.000\nPara\nNicolas Andrade\n...\nFecha y hora\n27/02/2026 12:06:28

  Transferencia entrante (noreply@correo.bancoestado.cl):
    "Has recibido una Transferencia Electrónica de nuestro(a) cliente NOMBRE"
    misma estructura campo-por-línea que la saliente
"""

from __future__ import annotations

import re

from models import TransactionRecord
from parsers.base import BankParser
from utils import normalize_clp_amount, parse_chilean_date


class BancoEstadoParser(BankParser):
    """Parser de correos Banco Estado (compras TC y transferencias)."""

    bank_name = "BANCO_ESTADO"
    # @bancoestado.cl no coincide con @correo.bancoestado.cl → usar dominio sin @
    sender_patterns = ("bancoestado.cl",)

    # Compra TC: "compra por $ X en MERCHANT ... el día DD/MM/YYYY"
    _PATTERN_COMPRA = re.compile(
        r"compra\s+por\s+\$\s*(?P<amount>[\d\.]+)\s+en\s+(?P<merchant>.+?)"
        r"(?:\s+asociado.*?)?\s+el\s+d[ií]a\s+(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Transferencia (saliente o entrante): campo en una línea, valor en la siguiente
    # Captura "Para\nNAME" para salientes y "de nuestro(a) cliente\nNAME" para entrantes
    _PATTERN_TRANSFER = re.compile(
        r"Monto\s*[\n\r]\s*\$?\s*(?P<amount>[\d\.]+).*?"
        r"(?:Para|de\s+nuestro\(a\)\s+cliente)\s*[\n\r]?\s*(?P<merchant>[^\n\r]+?)[\n\r].*?"
        r"Fecha\s+y\s+hora\s*[\n\r]\s*(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Fallback: campo e inline en misma línea (etiqueta: valor)
    _PATTERN_LEGACY = re.compile(
        r"(?:Tipo|Glosa):\s*(?P<type>.+?)\s*[\n\r]"
        r"(?:Monto|Importe):\s*\$?(?P<amount>[\d\.\-]+)\s*[\n\r]"
        r"(?:Comercio|Descripci[oó]n):\s*(?P<merchant>.+?)\s*[\n\r]"
        r"(?:Fecha|Fecha\s+operaci[oó]n):\s*(?P<date>[^\n\r]+)",
        re.IGNORECASE | re.DOTALL,
    )

    def can_parse(self, sender: str, subject: str, body: str) -> bool:
        return any(p in sender.lower() for p in self.sender_patterns)

    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        # 1. Compra TC (notificación directa con monto en línea)
        m = self._PATTERN_COMPRA.search(body)
        if m:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type="Compra TC",
                merchant=m.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 2. Transferencia (formato campo-por-línea real)
        m = self._PATTERN_TRANSFER.search(body)
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

        # 3. Formato legado etiqueta:valor
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

        raise ValueError("No fue posible parsear correo Banco Estado")
