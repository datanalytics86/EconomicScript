"""Parser de correos BCI.

Soporta dos tipos de notificación:
  - Compra con tarjeta de crédito (from: contacto@bci.cl)
  - Aviso de transferencia de fondos (from: transferencias@bci.cl)

Formato real observado en muestras:
  TC:                    Monto $202.502 / Fecha 02/03/2026 / Comercio XXXXX
  Transferencia saliente: Monto transferido $100.000 / Nombre del destinatario XXX / Fecha de abono 01/03/2026
  Transferencia entrante: Razón social: EMPRESA SPA / Monto transferido: $ 1,380,000 / Fecha: 30/03/2025
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

    # Transferencia saliente — layout estándar
    # Monto transferido $100.000 / Nombre del destinatario XXX / Fecha de abono DD/MM/YYYY
    _PATTERN_TRANSFER = re.compile(
        r"Monto transferido\s*:?\s*\$?\s*(?P<amount>[\d\.,]+).*?"
        r"Nombre del destinatario\s*:?\s*(?P<merchant>[^\n]+).*?"
        r"Fecha de abono\s*:?\s*(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Auto-transferencia entre cuentas propias (sin Nombre del destinatario)
    # Realizaste una transferencia de fondos desde tu cuenta N° XXXX hacia tu cuenta N° YYYY
    # Monto transferido $148.286 / Fecha de abono\nDD/MM/YYYY
    _PATTERN_TRANSFER_SELF = re.compile(
        r"transferencia de fondos.*?hacia tu cuenta N[°o]?\s*(?P<dest>\d+).*?"
        r"Monto transferido\s*\$?(?P<amount>[\d\.]+).*?"
        r"Fecha de abono\s*\n\s*(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Transferencia entrante — layout campo-por-línea
    # Razón social:\nEMPRESA SPA\n...\nMonto transferido:\n$ 1,380,000\n...\nFecha:\nDD/MM/YYYY
    _PATTERN_TRANSFER_INCOMING = re.compile(
        r"Raz[oó]n\s+social\s*:?\s*\n\s*(?P<merchant>[^\n]+).*?"
        r"Monto\s+transferido\s*:?\s*\n?\s*\$?\s*(?P<amount>[\d\.,]+).*?"
        r"Fecha\s*:?\s*\n?\s*(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Comprobante de pago de tarjeta de crédito
    #   Monto pagado:\n$61,636\nTarjeta de crédito:\n****6326\nFecha:\n27/04/23
    _PATTERN_PAGO_TC = re.compile(
        r"Monto pagado\s*:?\s*\n\s*\$?(?P<amount>[\d\.,]+).*?"
        r"Tarjeta de cr[eé]dito\s*:?\s*\n\s*(?P<card>[^\n]+).*?"
        r"Fecha\s*:?\s*\n\s*(?P<date>\d{2}/\d{2}/\d{2,4})",
        re.IGNORECASE | re.DOTALL,
    )

    # Notificación de compra con tarjeta de crédito — cuatro layouts posibles:

    # Layout moneda extranjera (igual al moderno pero monto en USD/EUR/etc):
    #   Monto\nUSD 20,00\nFecha\n15/06/2023\nHora\nHH:MM horas\nComercio\nNOMBRE
    _PATTERN_TC_FX = re.compile(
        r"Monto\s*\n\s*(?P<currency>[A-Z]{3})\s+(?P<amount>[\d,\.]+).*?"
        r"Fecha\s*\n\s*(?P<date>\d{2}/\d{2}/\d{4}).*?"
        r"Comercio\s*(?::?\s*|\n\s*)(?P<merchant>[^\n]+)",
        re.IGNORECASE | re.DOTALL,
    )

    # Layout moderno (etiqueta sola en su línea, valor en la siguiente):
    #   Monto\n$12.199\nFecha\n04/03/2026\nHora\nHH:MM horas\nComercio\nNOMBRE
    _PATTERN_TC_LABEL = re.compile(
        r"Monto\s*\n\s*\$(?P<amount>[\d\.]+).*?"
        r"Fecha\s*\n\s*(?P<date>\d{2}/\d{2}/\d{4}).*?"
        r"Comercio\s*(?::?\s*|\n\s*)(?P<merchant>[^\n]+)",
        re.IGNORECASE | re.DOTALL,
    )
    # Layout HTML (email antiguo): secuencia Hora → merchant → Comercio en líneas separadas
    #   Hora 13:43 horas\nDP *FALABELLA.COM\nComercio\nSANTIAGO CL
    _PATTERN_TC_PRE = re.compile(
        r"Monto\s*:?\s*\$?(?P<amount>[\d\.]+).*?"
        r"Fecha\s*:?\s*(?P<date>\d{2}/\d{2}/\d{4}).*?"
        r"Hora\s+[^\n]+\s*\n\s*(?P<merchant>[^\n]+)\s*\n\s*Comercio",
        re.IGNORECASE | re.DOTALL,
    )
    # Layout inline (text/plain o colon): merchant en la misma línea que "Comercio"
    #   Comercio DP *FALABELLA.COM SANTIAGO CL  /  Comercio: LIDER EXPRESS 1234
    _PATTERN_TC_POST = re.compile(
        r"Monto\s*:?\s*\$?(?P<amount>[\d\.]+).*?"
        r"Fecha\s*:?\s*(?P<date>\d{2}/\d{2}/\d{4}).*?"
        r"Comercio\s*:?\s*(?P<merchant>[^\n]+)",
        re.IGNORECASE | re.DOTALL,
    )

    def can_parse(self, sender: str, subject: str, body: str) -> bool:
        if not any(p in sender.lower() for p in self.sender_patterns):
            return False
        subject_l = subject.lower()
        # Alertas de seguridad/acceso sin transacción financiera → ignorar
        _NON_TX_KEYWORDS = ("no autorizada", "acceso a información", "cambio de clave", "clave de internet")
        if any(kw in subject_l for kw in _NON_TX_KEYWORDS):
            return False
        # Respuestas a hilos de soporte → no son notificaciones automáticas
        if subject_l.startswith("re:"):
            return False
        body_l = body.lower()
        return (
            "notificación" in subject_l
            or "aviso de transferencia" in subject_l
            or "transacción" in body_l
            or "transferencia de fondos" in body_l
            or "realizaste una compra" in body_l
            or "tarjeta de crédito" in body_l
        )

    def parse(self, body: str, gmail_message_id: str) -> TransactionRecord:
        # Auto-transferencia entre cuentas propias — tiene prioridad (no tiene "Nombre del destinatario")
        match = self._PATTERN_TRANSFER_SELF.search(body)
        if match:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(match.group("date")),
                amount=normalize_clp_amount(match.group("amount")),
                type="Transferencia Propia",
                merchant=f"Cuenta propia {match.group('dest')}",
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # Transferencia entrante (Razón social como remitente) — tiene prioridad sobre saliente
        match = self._PATTERN_TRANSFER_INCOMING.search(body)
        if match:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(match.group("date")),
                amount=normalize_clp_amount(match.group("amount")),
                type="Transferencia Entrante",
                merchant=match.group("merchant").strip(),
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # Transferencia saliente (Nombre del destinatario)
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

        # Pago de tarjeta de crédito (antes de los patrones TC para evitar falso positivo)
        match = self._PATTERN_PAGO_TC.search(body)
        if match:
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(match.group("date")),
                amount=normalize_clp_amount(match.group("amount")),
                type="Pago TC",
                merchant=f"Pago TC {match.group('card').strip()}",
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # Compra en moneda extranjera (USD, EUR, etc.) — antes de los patrones CLP
        match = self._PATTERN_TC_FX.search(body)
        if match:
            currency = match.group("currency").upper()
            raw_fx = match.group("amount").replace(",", ".")
            return TransactionRecord(
                bank=self.bank_name,
                date=parse_chilean_date(match.group("date")),
                amount=round(float(raw_fx)),
                type="Compra TC FX",
                merchant=f"{currency} - {match.group('merchant').strip()}",
                source="gmail",
                raw_text=body,
                gmail_message_id=gmail_message_id,
            )

        # Primero intenta layout moderno (etiqueta en su línea), luego HTML legacy, luego inline
        for pattern in (self._PATTERN_TC_LABEL, self._PATTERN_TC_PRE, self._PATTERN_TC_POST):
            match = pattern.search(body)
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
