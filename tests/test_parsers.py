"""Tests unitarios de parsers de correos bancarios."""

from parsers.banco_estado import BancoEstadoParser
from parsers.bci import BCIParser
from parsers.security import SecurityParser


def test_bci_parser_tc_purchase() -> None:
    """Notificación real de compra con tarjeta de crédito BCI."""
    parser = BCIParser()
    body = """Hola
NICOLAS IGNACIO SEBASTIAN ANDRADE SOCIAS
Realizaste una compra
con tu tarjeta de crédito.

Número tarjeta crédito ****9406
Monto $202.502
Fecha 02/03/2026
Hora 11:13 horas
Comercio NEAT GASTO COMUN SAN FELIPE CL
Cuotas 6
"""
    tx = parser.parse(body, "tc1")
    assert tx.bank == "BCI"
    assert tx.amount == 202502
    assert tx.type == "Compra TC"
    assert "NEAT" in tx.merchant


def test_bci_parser_tc_with_colon() -> None:
    """Compra TC con formato alternativo (etiquetas con dos puntos)."""
    parser = BCIParser()
    body = """Realizaste una compra con tu tarjeta de crédito.
Monto: $45.890
Fecha: 15/01/2025
Hora: 14:32 horas
Comercio: LIDER EXPRESS 1234
Cuotas: 1
"""
    tx = parser.parse(body, "tc2")
    assert tx.amount == 45890
    assert tx.merchant == "LIDER EXPRESS 1234"


def test_bci_parser_transfer() -> None:
    """Notificación real de transferencia de fondos BCI."""
    parser = BCIParser()
    body = """Hola
Nicolas Ignacio Sebastian Andrade Socias
Realizaste una transferencia de fondos desde
tu cuenta N° 46685197

Datos de tu transferencia
Monto transferido $100.000
Nombre del destinatario Kathia Silva
Banco de destino Banco de Chile / Edwards / Credichile
Cuenta de destino 8002066409
Fecha de abono 01/03/2026
Número de comprobante 1134563970
"""
    tx = parser.parse(body, "tr1")
    assert tx.bank == "BCI"
    assert tx.amount == 100000
    assert tx.type == "Transferencia"
    assert tx.merchant == "Kathia Silva"


def test_bci_can_parse_transfer_subject() -> None:
    parser = BCIParser()
    assert parser.can_parse("transferencias@bci.cl", "Aviso de Transferencia de Fondos.", "")


def test_bci_can_parse_tc_subject() -> None:
    parser = BCIParser()
    assert parser.can_parse(
        "contacto@bci.cl", "Notificación de uso de tu tarjeta de crédito", ""
    )


def test_bci_can_parse_rejects_other_sender() -> None:
    parser = BCIParser()
    assert not parser.can_parse("noreply@gmail.com", "Aviso de Transferencia", "")


def test_banco_estado_parser_case_1() -> None:
    parser = BancoEstadoParser()
    body = """Tipo: Compra Débito
Monto: $23.450
Comercio: SANTA ISABEL
Fecha: 15/01/2025 11:12
"""
    tx = parser.parse(body, "e1")
    assert tx.bank == "BANCO_ESTADO"


def test_banco_estado_parser_case_2() -> None:
    parser = BancoEstadoParser()
    body = """Glosa: Transferencia
Importe: $300.000
Descripción: PAGO ARRIENDO
Fecha operación: 14-01-2025
"""
    tx = parser.parse(body, "e2")
    assert tx.amount == 300000


def test_banco_estado_parser_case_3() -> None:
    parser = BancoEstadoParser()
    body = """Tipo: Compra Web
Monto: $19.990
Comercio: MERCADOLIBRE
Fecha: 18/01/2025 08:45
"""
    tx = parser.parse(body, "e3")
    assert tx.type == "Compra Web"


def test_security_parser_case_1() -> None:
    parser = SecurityParser()
    body = """Movimiento: Compra
Monto: $55.000
Comercio: COPEC
Fecha: 19/01/2025 10:00
"""
    tx = parser.parse(body, "s1")
    assert tx.bank == "SECURITY"


def test_security_parser_case_2() -> None:
    parser = SecurityParser()
    body = """Tipo: Cargo
Total: $14.500
Detalle: UBER TRIP
Fecha y hora: 20-01-2025 23:15
"""
    tx = parser.parse(body, "s2")
    assert tx.amount == 14500


def test_security_parser_case_3() -> None:
    parser = SecurityParser()
    body = """Movimiento: Suscripción
Monto: $6.990
Comercio: SPOTIFY
Fecha: 21/01/2025
"""
    tx = parser.parse(body, "s3")
    assert tx.merchant == "SPOTIFY"
