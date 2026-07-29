"""Tests del ciclo de gasto (día 27 de cada mes)."""

from datetime import date

from utils import CYCLE_START_DAY, get_cycle_label, get_cycle_start_date


def test_cycle_start_day_constant() -> None:
    assert CYCLE_START_DAY == 27


def test_cycle_start_febrero_2026() -> None:
    # 3/mar → ciclo desde 27/feb
    assert get_cycle_start_date(today=date(2026, 3, 3)) == date(2026, 2, 27)


def test_cycle_start_enero_2025() -> None:
    assert get_cycle_start_date(today=date(2025, 2, 1)) == date(2025, 1, 27)


def test_cycle_start_septiembre_2025() -> None:
    assert get_cycle_start_date(today=date(2025, 10, 1)) == date(2025, 9, 27)


def test_cycle_start_diciembre_2025() -> None:
    assert get_cycle_start_date(today=date(2026, 1, 5)) == date(2025, 12, 27)


def test_cycle_start_on_the_27th() -> None:
    assert get_cycle_start_date(today=date(2026, 7, 27)) == date(2026, 7, 27)


def test_cycle_start_before_27() -> None:
    assert get_cycle_start_date(today=date(2026, 7, 15)) == date(2026, 6, 27)


def test_cycle_start_sin_argumento_retorna_date() -> None:
    result = get_cycle_start_date()
    assert isinstance(result, date)


def test_cycle_label_names() -> None:
    assert get_cycle_label(date(2026, 7, 29)) == "Agosto"
    assert get_cycle_label(date(2026, 8, 27)) == "Septiembre"
