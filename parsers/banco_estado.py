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
from datetime import datetime

from models import TransactionRecord
from parsers.base import BankParser
from utils import SANTIAGO_TZ, normalize_clp_amount, parse_chilean_date


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

    # Cobro pasaje QR RED: "cobro por $895 en tu cuenta ... Pasaje QR"
    # Muchos mails no traen fecha en el body → fallback a "hoy" (America/Santiago).
    _PATTERN_COBRO_PASAJE = re.compile(
        r"cobro\s+por\s+\$\s*(?P<amount>[\d\.]+)\s+en\s+tu\s+cuenta"
        r".*?(?:Pasaje\s*QR|viajes\s+pagados\s+con\s+Pasaje)",
        re.IGNORECASE | re.DOTALL,
    )

    # Anulación / reverso TC (misma estructura que compra)
    # "Se ha realizado una anulación por $ X en MERCHANT ... el día DD/MM/YYYY"
    _PATTERN_ANULACION = re.compile(
        r"(?:anulaci[oó]n|reverso|devoluci[oó]n)\s+por\s+\$\s*(?P<amount>[\d\.]+)\s+en\s+"
        r"(?P<merchant>.+?)(?:\s+asociado.*?)?\s+el\s+d[ií]a\s+(?P<date>\d{2}/\d{2}/\d{4})",
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

    # TEF comprobante (orden real varía: a veces Fecha antes de Nombre/Hacia)
    # Monto transferido:\n $20.000 ... Fecha y Hora de TEF:24/07/2026 ... Nombre:Lidia
    _PATTERN_TEF = re.compile(
        r"Monto\s+transferido\s*:?\s*\$?\s*(?P<amount>[\d\.,]+).*?"
        r"Fecha\s+y\s+[Hh]ora(?:\s+de\s+TEF)?\s*:?\s*(?P<date>\d{2}/\d{2}/\d{4})"
        r"(?:.*?Nombre\s*:?\s*(?P<merchant>[^\n\r]+))?",
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

    # Comprobante compacto: "Total pagado$5.148 ... Fecha y hora12/07/2026 16:59"
    # (sin espacios entre etiqueta y valor; sin campo Producto)
    _PATTERN_PAGO_COMPACT = re.compile(
        r"(?:Total\s*pagado|Monto\s*pagado)\s*\$?\s*(?P<amount>[\d\.,]+).*?"
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
        if not any(p in sender.lower() for p in self.sender_patterns):
            return False
        text = f"{subject} {body}".lower()
        tx_keywords = (
            "compra",
            "transferencia",
            "monto",
            "pago de producto",
            "pago",
            "cargo",
            "abono",
            "recibiste",
            "realizaste",
            "anulación",
            "anulacion",
            "reverso",
            "devolución",
            "devolucion",
            "cobro",
            "pasaje",
            "tef",
        )
        return any(kw in text for kw in tx_keywords)

    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        # 0. Anulación / reverso TC — prioriza sobre compra
        m = self._PATTERN_ANULACION.search(body)
        if m:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=-abs(normalize_clp_amount(m.group("amount"))),
                type="Anulación TC",
                merchant=m.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

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

        # 2b. Comprobante de pago compacto (sin campo Producto)
        m = self._PATTERN_PAGO_COMPACT.search(body)
        if m and ("pago de producto" in body.lower() or "total pagado" in body.lower()):
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type="Pago Producto",
                merchant="Pago producto BancoEstado",
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 3. TEF comprobante (envío/recepción) — antes del transfer genérico
        m = self._PATTERN_TEF.search(body)
        if m:
            merchant = (m.group("merchant") or "Transferencia BancoEstado").strip()
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(m.group("date")),
                amount=normalize_clp_amount(m.group("amount")),
                type="Transferencia",
                merchant=merchant,
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # 3b. Transferencia (formato campo-por-línea real)
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

        # 3c. Cobro pasaje QR RED (débito cuenta corriente; gasto de consumo)
        m = self._PATTERN_COBRO_PASAJE.search(body)
        if m:
            # Preferir cualquier fecha DD/MM/YYYY presente; si no, hoy (mail suele ser D+1)
            date_m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", body)
            tx_date = (
                parse_chilean_date(date_m.group(1))
                if date_m
                else datetime.now(tz=SANTIAGO_TZ)
            )
            return TransactionRecord(
                bank=self.bank_name,
                date=tx_date,
                amount=normalize_clp_amount(m.group("amount")),
                type="Compra TC",
                merchant="Pasaje QR RED BancoEstado",
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
