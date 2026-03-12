"""Tests unitarios de parsers bancarios y statement_parser."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parsers.banco_estado import BancoEstadoParser
from parsers.bci import BCIParser
from parsers.security import SecurityParser
from statement_parser import StatementParser
from utils import normalize_clp_amount, parse_chilean_date

# ─────────────────────────────────────────────
# utils
# ─────────────────────────────────────────────

def test_normalize_amount_standard() -> None:
    assert normalize_clp_amount("$1.234") == 1234

def test_normalize_amount_dollar_space_negative() -> None:
    """Formato EECC: '$ -4.446.270'"""
    assert normalize_clp_amount("$ -4.446.270") == -4446270

def test_normalize_amount_negative_prefix() -> None:
    assert normalize_clp_amount("-$100.000") == -100000

def test_parse_date_short_year() -> None:
    """Año corto DD/MM/YY usado en EECC."""
    dt = parse_chilean_date("30/01/26")
    assert dt.year == 2026
    assert dt.month == 1
    assert dt.day == 30

def test_parse_date_with_seconds() -> None:
    """Fecha con hora y segundos de transferencias BancoEstado."""
    dt = parse_chilean_date("27/02/2026 12:06")
    assert dt.year == 2026

# ─────────────────────────────────────────────
# BCI
# ─────────────────────────────────────────────

def test_bci_tc_real_format() -> None:
    """Compra TC real: campo y valor en la misma línea separados por espacio."""
    parser = BCIParser()
    body = (
        "Hola\n"
        "NICOLAS IGNACIO SEBASTIAN ANDRADE SOCIAS\n"
        "Realizaste una compra\n"
        "con tu tarjeta de crédito.\n\n"
        "Número tarjeta crédito ****9406\n"
        "Monto $73.970\n"
        "Fecha 02/03/2026\n"
        "Hora 13:43 horas\n"
        "Comercio DP *FALABELLA.COM SANTIAGO CL\n"
        "Cuotas 3\n"
    )
    tx = parser.parse(body, "bci_tc_1")
    assert tx.bank == "BCI"
    assert tx.amount == 73970
    assert tx.type == "Compra TC"
    assert "FALABELLA" in tx.merchant


def test_bci_tc_legacy_colon_format() -> None:
    """Compra TC con formato de etiqueta:valor."""
    parser = BCIParser()
    body = (
        "Realizaste una compra con tu tarjeta de crédito.\n"
        "Monto: $45.890\n"
        "Fecha: 15/01/2025\n"
        "Hora: 14:32 horas\n"
        "Comercio: LIDER EXPRESS 1234\n"
        "Cuotas: 1\n"
    )
    tx = parser.parse(body, "bci_tc_2")
    assert tx.amount == 45890
    assert tx.merchant == "LIDER EXPRESS 1234"


def test_bci_transfer_real_format() -> None:
    """Transferencia BCI real: campos en una línea."""
    parser = BCIParser()
    body = (
        "Hola\nNicolas Ignacio Sebastian Andrade Socias\n"
        "Realizaste una transferencia de fondos desde\n"
        "tu cuenta N° 46685197\n\n"
        "Datos de tu transferencia\n"
        "Monto transferido $4.000.000\n"
        "Nombre del destinatario Nicolas Andrade\n"
        "Banco de destino Banco Security\n"
        "Cuenta de destino 927174470\n"
        "Fecha de abono 02/03/2026\n"
        "Número de comprobante 1135224638\n"
    )
    tx = parser.parse(body, "bci_tr_1")
    assert tx.bank == "BCI"
    assert tx.amount == 4000000
    assert tx.type == "Transferencia"
    assert tx.merchant == "Nicolas Andrade"


def test_bci_transfer_incoming_format() -> None:
    """Transferencia entrante BCI: Razón social como remitente, montos con coma."""
    parser = BCIParser()
    body = (
        "Hola\nnicolas andrade\n"
        "Has recibido una transferencia de fondos de DEEP PRO BUSINESS SOLUTIO NS SPA "
        "hacia tu cuenta del BCI-TBANC-NOVA.\n"
        "Detalle de la transferencia\n"
        "Origen\n"
        "Razón social:\n"
        "DEEP PRO BUSINESS SOLUTIO NS SPA\n"
        "RUT:\n"
        "77923111-9\n"
        "Cuenta:\n"
        "BCI/TBANC/NOVA\n"
        "Destino\n"
        "Nombre:\n"
        "nicolas andrade\n"
        "Monto transferido:\n"
        "$ 1,380,000\n"
        "Nº de cuenta:\n"
        "000000000046685197\n"
        "Banco:\n"
        "BCI-TBANC-NOVA\n"
        "Nº de comprobante:\n"
        "94103078\n"
        "Fecha:\n"
        "30/03/2025\n"
        "Hora:\n"
        "14:20\n"
    )
    tx = parser.parse(body, "bci_tr_incoming_1")
    assert tx.bank == "BCI"
    assert tx.amount == 1380000
    assert tx.type == "Transferencia Entrante"
    assert tx.merchant == "DEEP PRO BUSINESS SOLUTIO NS SPA"
    assert tx.date.day == 30
    assert tx.date.month == 3
    assert tx.date.year == 2025


def test_bci_can_parse_transfer_sender() -> None:
    assert BCIParser().can_parse("transferencias@bci.cl", "Aviso de Transferencia de Fondos.", "")


def test_bci_can_parse_tc_sender() -> None:
    assert BCIParser().can_parse("contacto@bci.cl", "Notificación de uso de tu tarjeta", "")


def test_bci_rejects_other_sender() -> None:
    assert not BCIParser().can_parse("noreply@gmail.com", "Aviso", "")


def test_bci_can_parse_rejects_compra_no_autorizada() -> None:
    assert not BCIParser().can_parse("contacto@bci.cl", "Notificación de compra no autorizada", "")


def test_bci_can_parse_rejects_acceso_informacion() -> None:
    assert not BCIParser().can_parse("contacto@bci.cl",
        "Notificación de acceso a información de Tarjeta de Débito", "")


def test_bci_transfer_self() -> None:
    """Auto-transferencia entre cuentas propias: sin 'Nombre del destinatario'."""
    parser = BCIParser()
    body = (
        "Hola\n"
        "Nicolas Ignacio Sebastian Andrade Socias\n"
        "Realizaste una transferencia de fondos desde tu cuenta N° 67940684\n"
        "hacia tu cuenta N° 46685197\n"
        "Datos de tu transferencia\n"
        "Monto transferido $148.286\n"
        "Cuenta de destino\n"
        "46685197\n"
        "Fecha de abono\n"
        "17/05/2023\n"
        "Mensaje\n"
        "Número de comprobante\n"
        "689586460\n"
    )
    tx = parser.parse(body, "msg-self-001")
    assert tx.type == "Transferencia Propia"
    assert tx.amount == 148286
    assert tx.merchant == "Cuenta propia 46685197"
    assert tx.date.day == 17
    assert tx.date.month == 5
    assert tx.date.year == 2023


def test_bci_pago_tc() -> None:
    """Comprobante pago tarjeta de crédito: 'Monto pagado:' y 'Tarjeta de crédito:'."""
    parser = BCIParser()
    body = (
        "Hola\n"
        "Nicolas Ignacio Sebastian Andrade Socias\n"
        "Has realizado el siguiente pago de tu tarjeta de crédito nacional:\n"
        "Detalle del pago\n"
        "Monto pagado:\n"
        "$61,636\n"
        "Cuenta de origen:\n"
        "46685197\n"
        "Tarjeta de crédito:\n"
        "****6326\n"
        "Fecha:\n"
        "27/04/23\n"
        "Hora:\n"
        "07:05\n"
    )
    tx = parser.parse(body, "msg-pago-001")
    assert tx.type == "Pago TC"
    assert tx.amount == 61636
    assert tx.merchant == "Pago TC ****6326"
    assert tx.date.day == 27
    assert tx.date.month == 4
    assert tx.date.year == 2023


def test_bci_tc_fx_usd() -> None:
    """Compra TC en moneda extranjera (USD): layout moderno con monto USD XX,XX."""
    parser = BCIParser()
    body = (
        "Notificación uso TDC\n"
        "Hola\n"
        "NICOLAS IGNACIO SEBASTIAN ANDRADE SOCIAS\n"
        "Realizaste una\n"
        "compra en comercio internacional\n"
        "con tu\n"
        "tarjeta de crédito.\n"
        "Número tarjeta crédito\n"
        "****1022\n"
        "Monto\n"
        "USD 20,00\n"
        "Fecha\n"
        "15/06/2023\n"
        "Hora\n"
        "12:28 horas\n"
        "Comercio\n"
        "CHATGPT SUBSCRIPTION +14158799686 US\n"
    )
    tx = parser.parse(body, "msg-fx-001")
    assert tx.type == "Compra TC FX"
    assert tx.amount == 20
    assert tx.merchant == "USD - CHATGPT SUBSCRIPTION +14158799686 US"
    assert tx.date.day == 15
    assert tx.date.month == 6
    assert tx.date.year == 2023


def test_bci_tc_fx_decimal() -> None:
    """Compra TC FX con centavos: USD 37,20 → amount=37."""
    parser = BCIParser()
    body = (
        "Monto\n"
        "USD 37,20\n"
        "Fecha\n"
        "11/06/2023\n"
        "Hora\n"
        "22:08 horas\n"
        "Comercio\n"
        "BEAU SOIR MONTREAL CA\n"
    )
    tx = parser.parse(body, "msg-fx-002")
    assert tx.type == "Compra TC FX"
    assert tx.amount == 37
    assert "BEAU SOIR MONTREAL CA" in tx.merchant


# ─────────────────────────────────────────────
# BancoEstado
# ─────────────────────────────────────────────

def test_bancoestado_compra_tc_real() -> None:
    """Compra TC real BancoEstado: monto y merchant en una sola línea."""
    parser = BancoEstadoParser()
    body = (
        "NICOLAS IGNACIO SEBASTIAN ANDRADE\n"
        "Se ha realizado una compra por $ 2.990 en MERPAGO*MELIMAS asociado a su "
        "tarjeta de crédito terminada en **** 0608 el día 27/02/2026 a las 15:12 hrs.\n"
    )
    tx = parser.parse(body, "be_tc_1")
    assert tx.bank == "BANCO_ESTADO"
    assert tx.amount == 2990
    assert tx.type == "Compra TC"
    assert "MERPAGO" in tx.merchant


def test_bancoestado_transfer_saliente_real() -> None:
    """Transferencia saliente BancoEstado: campo por línea."""
    parser = BancoEstadoParser()
    body = (
        "Estimado(a) Nicolas Ignacio Sebastian Andrade:\n"
        "La transferencia se ha realizado con éxito\n"
        "Datos de la transferencia que realizaste\n"
        "Monto\n"
        "$1.200.000\n"
        "Para\n"
        "Nicolas Andrade\n"
        "RUT\n"
        "16.474.276-8\n"
        "Cuenta\n"
        "Cuenta Corriente 46685197\n"
        "Banco\n"
        "BANCO DE CREDITO E INVERSIONES\n"
        "Email\n"
        "andrade.nico@gmail.com\n"
        "Desde\n"
        "Cuenta Corriente 28200260921\n"
        "Mensaje\n"
        "Fecha y hora\n"
        "27/02/2026 12:06:28\n"
        "N° transacción\n"
        "7084964\n"
    )
    tx = parser.parse(body, "be_tr_1")
    assert tx.bank == "BANCO_ESTADO"
    assert tx.amount == 1200000
    assert tx.type == "Transferencia"
    assert tx.merchant == "Nicolas Andrade"


def test_bancoestado_transfer_entrante_real() -> None:
    """Transferencia entrante BancoEstado: campo 'de nuestro(a) cliente'."""
    parser = BancoEstadoParser()
    body = (
        "Estimado(a) Nicolas Andrade:\n"
        "Has recibido una Transferencia Electrónica\n"
        "de nuestro(a) cliente Nicolas Ignacio Sebastian Andrade\n"
        "Datos de la transferencia que recibiste\n"
        "Monto\n"
        "$1.200.000\n"
        "Para\n"
        "Nicolas Andrade\n"
        "RUT\n"
        "16.474.276-8\n"
        "Fecha y hora\n"
        "27/02/2026 12:06:28\n"
    )
    tx = parser.parse(body, "be_tr_2")
    assert tx.amount == 1200000
    assert "Nicolas" in tx.merchant


def test_bancoestado_legacy_format() -> None:
    """Formato legado etiqueta:valor sigue funcionando."""
    parser = BancoEstadoParser()
    body = "Tipo: Compra Débito\nMonto: $23.450\nComercio: SANTA ISABEL\nFecha: 15/01/2025 11:12\n"
    tx = parser.parse(body, "be_leg_1")
    assert tx.bank == "BANCO_ESTADO"
    assert tx.amount == 23450


def test_bancoestado_can_parse_real_sender() -> None:
    """Acepta remitentes reales de BancoEstado."""
    parser = BancoEstadoParser()
    assert parser.can_parse("notificaciones@correo.bancoestado.cl", "", "")
    assert parser.can_parse("noreply@correo.bancoestado.cl", "", "")


def test_bancoestado_rejects_other_sender() -> None:
    assert not BancoEstadoParser().can_parse("spam@gmail.com", "", "")


# ─────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────

def test_security_compra_tc_real() -> None:
    """Compra TC real Security: 'El DD/MM/YYYY ... realizaste una compra en MERCHANT de $X'."""
    parser = SecurityParser()
    body = (
        "Estimado(a) NICOLAS IGNACIO S. ANDRADE SOCIAS,\n"
        "El 03/03/2026 a las 09:41 realizaste una compra en\n"
        "RedGloba*STOP MARKET PROVIDENCIA CHL de $2.990 con\n"
        "cargo a la tarjeta ***7233.\n"
    )
    tx = parser.parse(body, "sec_tc_1")
    assert tx.bank == "SECURITY"
    assert tx.amount == 2990
    assert tx.type == "Compra TC"
    assert "STOP MARKET" in tx.merchant


def test_security_transfer_saliente_real() -> None:
    """Transferencia saliente Security: Monto: → Fecha y hora: → Nombre:."""
    parser = SecurityParser()
    body = (
        "Comprobante de transferencia\n"
        "Estimado(a) NICOLAS IGNACIO S. ANDRADE SOCIAS\n"
        "Usted realizó la siguiente transferencia de fondos:\n"
        "Datos de Transferencia\n"
        "Monto:\n"
        "$ 2.500.000\n"
        "Motivo:\n"
        "pagos\n"
        "Cuenta de origen:\n"
        "927174470\n"
        "Fecha y hora:\n"
        "02/03/2026 16:00 hrs.\n"
        "N° de operación:\n"
        "00883682844\n"
        "Datos de Destinatario\n"
        "Nombre:\n"
        "Nicolas Andrade Socias\n"
        "Rut:\n"
        "16.474.276-8\n"
    )
    tx = parser.parse(body, "sec_tr_1")
    assert tx.bank == "SECURITY"
    assert tx.amount == 2500000
    assert tx.type == "Transferencia"
    assert "Nicolas Andrade" in tx.merchant


def test_security_transfer_entrante_real() -> None:
    """Transferencia entrante Security: 'recibiste una TRANSFERENCIA DESDE BANCO DE NOMBRE'."""
    parser = SecurityParser()
    body = (
        "Estimado(a) NICOLAS IGNACIO S. ANDRADE SOCIAS,\n"
        "El 02/03/2026 a las 18:46 recibiste una TRANSFERENCIA DESDE\n"
        "BCI DE Nicolas Ignacio Sebastian Andrade Socias en la cuenta\n"
        "***4470 de $1.000.000.\n"
    )
    tx = parser.parse(body, "sec_tr_2")
    assert tx.bank == "SECURITY"
    assert tx.amount == 1000000
    assert tx.type == "Transferencia Recibida"
    assert "Nicolas" in tx.merchant


def test_security_legacy_format() -> None:
    """Formato legado etiqueta:valor sigue funcionando."""
    parser = SecurityParser()
    body = "Movimiento: Compra\nMonto: $55.000\nComercio: COPEC\nFecha: 19/01/2025 10:00\n"
    tx = parser.parse(body, "sec_leg_1")
    assert tx.bank == "SECURITY"
    assert tx.amount == 55000


def test_security_can_parse_purchase_sender() -> None:
    assert SecurityParser().can_parse("notificaciones@security.cl", "", "")


def test_security_can_parse_transfer_sender() -> None:
    assert SecurityParser().can_parse("noresponder@bancosecurity.cl", "", "")


def test_security_rejects_other_sender() -> None:
    assert not SecurityParser().can_parse("noreply@gmail.com", "", "")


# ─────────────────────────────────────────────
# StatementParser — PDFs reales del dropzone
# ─────────────────────────────────────────────

DROPZONE = Path(__file__).resolve().parents[1] / "samples" / "dropzone"


def _pdf(name: str) -> Path:
    return DROPZONE / name


@pytest.mark.skipif(
    not _pdf("Cartola_BancoEstado_SinPassword.pdf").exists(),
    reason="Archivo de muestra no encontrado",
)
def test_statement_cartola_bancoestado() -> None:
    """Cartola BancoEstado extrae todas las filas de la tabla correctamente."""
    txs = StatementParser().parse_file(str(_pdf("Cartola_BancoEstado_SinPassword.pdf")))
    assert len(txs) >= 7, f"Se esperaban >= 7 transacciones, se obtuvieron {len(txs)}"
    banks = {tx.bank for tx in txs}
    assert banks == {"BANCO_ESTADO"}
    # Verifica cargos y abonos
    tipos = {tx.type for tx in txs}
    assert "Cargo" in tipos
    assert "Abono" in tipos


@pytest.mark.skipif(
    not _pdf("EECC_VISA_BancoEstado_SinPassword.pdf").exists(),
    reason="Archivo de muestra no encontrado",
)
def test_statement_eecc_bancoestado() -> None:
    """EECC BancoEstado extrae transacciones del período actual."""
    txs = StatementParser().parse_file(str(_pdf("EECC_VISA_BancoEstado_SinPassword.pdf")))
    assert len(txs) >= 3, f"Se esperaban >= 3 transacciones, se obtuvieron {len(txs)}"
    banks = {tx.bank for tx in txs}
    assert banks == {"BANCO_ESTADO"}
    merchants = [tx.merchant for tx in txs]
    assert any("NETFLIX" in m.upper() or "MERPAGO" in m.upper() or "FUNDACION" in m.upper()
               for m in merchants)


@pytest.mark.skipif(
    not _pdf("EECC_VISA_Security_SinPassword.pdf").exists(),
    reason="Archivo de muestra no encontrado",
)
def test_statement_eecc_security() -> None:
    """EECC Security extrae transacciones del período actual."""
    txs = StatementParser().parse_file(str(_pdf("EECC_VISA_Security_SinPassword.pdf")))
    assert len(txs) >= 5, f"Se esperaban >= 5 transacciones, se obtuvieron {len(txs)}"
    banks = {tx.bank for tx in txs}
    assert banks == {"SECURITY"}


@pytest.mark.skipif(
    not _pdf("EECC_VISA_BCI_SinPassword.pdf").exists(),
    reason="Archivo de muestra no encontrado",
)
def test_statement_eecc_bci() -> None:
    """EECC BCI extrae transacciones del período actual (incluye cargos en cuotas e impuestos)."""
    txs = StatementParser().parse_file(str(_pdf("EECC_VISA_BCI_SinPassword.pdf")))
    assert len(txs) >= 10, f"Se esperaban >= 10 transacciones, se obtuvieron {len(txs)}"
    banks = {tx.bank for tx in txs}
    assert banks == {"BCI"}
    # Hay abonos (pagos) y cargos
    tipos = {tx.type for tx in txs}
    assert "Cargo TC" in tipos or "Abono TC" in tipos
