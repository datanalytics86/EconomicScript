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

    # Transferencia (saliente o entrante)
    # Dos layouts reales:
    #   Con espacios: "Monto $1.200.000 \n Para Nicolas Andrade \n ... 27/02/2026"
    #   Sin espacios: "Monto$1.300,000\nParaNicolas Andrade\n...19/06/2023 14:25"
    _PATTERN_TRANSFER = re.compile(
        r"Monto\s*\$?\s*(?P<amount>[\d\.,]+).*?"
        r"(?:Para|de\s+nuestro\(a\)\s+cliente)\s*(?P<merchant>[^\n\r]+).*?"
        r"(?:Fecha\s+y\s+hora\s*:?\s*)?(?P<date>\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)",
        re.IGNORECASE | re.DOTALL,
    )

    # Compra en moneda extranjera (CAD, USD, EUR, etc.) con layout multilinea
    #   "compra por CAD\n137,43\n en\nPHARMAPRIX 42\n...el día\n20/06/2023"
    _PATTERN_COMPRA_FX = re.compile(
        r"compra\s+por\s+(?P<currency>[A-Z]{2,3})\s*\n\s*(?P<amount>[\d,\.]+).*?"
        r"en\s*\n\s*(?P<merchant>[^\n]+).*?"
        r"el\s+d[ií]a\s*\n?\s*(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Pago de producto: cuota crédito, pago tarjeta, etc.
    # "has realizado un pago de producto: ... Monto pagado:$X ... Fecha y hora: DD/MM/YYYY"
    _PATTERN_PAGO = re.compile(
        r"pago de producto.*?"
        r"Producto\s*:?\s*(?P<merchant>[^\n]+).*?"
        r"Monto pagado\s*:?\s*\$?(?P<amount>[\d\.]+).*?"
        r"Fecha\s*y\s*hora\s*:?\s*(?P<date>\d{2}/\d{2}/\d{4})",
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
        # 1. Compra TC en moneda extranjera (CAD/USD/EUR) — layout multilinea
        m = self._PATTERN_COMPRA_FX.search(body)
        if m:
            currency = m.group("currency").upper()
            raw_fx = m.group("amount").replace(",", ".")
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=round(float(raw_fx)),
                type="Compra TC FX",
                merchant=f"{currency} - {m.group('merchant').strip()}",
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 2. Compra TC CLP (notificación directa con monto en línea)
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

        # 2. Pago de producto (cuota crédito, pago tarjeta, etc.)
        m = self._PATTERN_PAGO.search(body)
        if m:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type="Pago Producto",
                merchant=m.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 3. Transferencia (formato campo-por-línea real)
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

        # 4. Formato legado etiqueta:valor
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
