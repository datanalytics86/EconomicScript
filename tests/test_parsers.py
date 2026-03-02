"""Tests unitarios de parsers de correos bancarios."""

from parsers.banco_estado import BancoEstadoParser
from parsers.bci import BCIParser
from parsers.security import SecurityParser


def test_bci_parser_case_1() -> None:
    parser = BCIParser()
    body = """Se ha realizado la siguiente transacción:
Tipo: Compra Nacional
Monto: $45.890
Comercio: LIDER EXPRESS 1234
Tarjeta: **** 5678
Fecha: 15/01/2025 14:32
"""
    tx = parser.parse(body, "m1")
    assert tx.bank == "BCI"
    assert tx.amount == 45890


def test_bci_parser_case_2() -> None:
    parser = BCIParser()
    body = """Tipo: Pago Servicio
Monto: $1.250.000
Comercio: AGUAS ANDINAS
Tarjeta: **** 1234
Fecha: 16-01-2025 09:10
"""
    tx = parser.parse(body, "m2")
    assert tx.amount == 1250000


def test_bci_parser_case_3() -> None:
    parser = BCIParser()
    body = """Tipo: Compra Internacional
Monto: $9.990
Comercio: NETFLIX
Tarjeta: **** 1111
Fecha: 17/01/2025
"""
    tx = parser.parse(body, "m3")
    assert tx.merchant == "NETFLIX"


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
