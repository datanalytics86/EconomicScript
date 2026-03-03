"""Tests para get_cycle_start_date — verifica integración con holidays.CL."""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import get_cycle_start_date


# ─────────────────────────────────────────────
# Importación de la librería
# ─────────────────────────────────────────────

def test_holidays_importa_correctamente():
    """holidays se importa sin error y holidays.CL existe."""
    import holidays as holidays_lib
    assert hasattr(holidays_lib, "CL"), "holidays.CL no existe"


def test_holidays_cl_instancia_correctamente():
    """holidays.CL(years=2025) retorna un objeto con fechas de Chile."""
    import holidays as holidays_lib
    cl = holidays_lib.CL(years=2025)
    assert isinstance(cl, dict)


# ─────────────────────────────────────────────
# Feriados chilenos conocidos
# ─────────────────────────────────────────────

@pytest.mark.parametrize("holiday_date,nombre", [
    (date(2025, 1, 1),  "Año Nuevo"),
    (date(2025, 5, 1),  "Día del Trabajo"),
    (date(2025, 9, 18), "Fiestas Patrias"),
    (date(2025, 9, 19), "Día del Ejército"),
    (date(2025, 12, 25), "Navidad"),
    (date(2025, 12, 8),  "Inmaculada Concepción"),
])
def test_feriados_chilenos_reconocidos(holiday_date, nombre):
    """holidays.CL reconoce los feriados legales chilenos principales."""
    import holidays as holidays_lib
    cl = holidays_lib.CL(years=holiday_date.year)
    assert holiday_date in cl, f"{nombre} ({holiday_date}) no encontrado en holidays.CL"


# ─────────────────────────────────────────────
# get_cycle_start_date: casos sin feriados al final del mes
# ─────────────────────────────────────────────

def test_cycle_start_febrero_2026():
    """Feb 28 2026 = sábado → 1er hábil = 27 feb (vie), 2do hábil = 26 feb (jue)."""
    # Verificación manual: Jan 1 2026 = Thursday → Feb 1 = Sunday → Feb 28 = Saturday
    assert date(2026, 2, 28).weekday() == 5  # sábado
    result = get_cycle_start_date(today=date(2026, 3, 3))
    assert result == date(2026, 2, 26)


def test_cycle_start_enero_2025():
    """Jan 31 2025 = viernes (hábil), Jan 30 = jueves (hábil) → inicio = Jan 30."""
    assert date(2025, 1, 31).weekday() == 4  # viernes
    result = get_cycle_start_date(today=date(2025, 2, 1))
    assert result == date(2025, 1, 30)


def test_cycle_start_septiembre_2025():
    """Sep 30 2025 = martes (hábil), Sep 29 = lunes (hábil) → inicio = Sep 29.

    Sep 18 y 19 son feriados pero caen a mitad de mes, no afectan el resultado.
    """
    assert date(2025, 9, 30).weekday() == 1  # martes
    assert date(2025, 9, 29).weekday() == 0  # lunes
    result = get_cycle_start_date(today=date(2025, 10, 1))
    assert result == date(2025, 9, 29)


def test_cycle_start_diciembre_2025():
    """Dec 31 2025 = miércoles (hábil), Dec 30 = martes (hábil) → inicio = Dec 30."""
    assert date(2025, 12, 31).weekday() == 2  # miércoles
    result = get_cycle_start_date(today=date(2026, 1, 5))
    assert result == date(2025, 12, 30)


# ─────────────────────────────────────────────
# get_cycle_start_date: feriado al final del mes (mock)
# ─────────────────────────────────────────────

def test_cycle_start_omite_feriado_al_final():
    """Si el último día hábil del mes es feriado, se salta y busca el anterior.

    Escenario: dic 31 2025 (mié) es feriado ficticio.
      → 1er hábil = dic 30 (mar), 2do hábil = dic 29 (lun) → inicio = dic 29
    """
    fake_holidays = {date(2025, 12, 31): "Feriado ficticio"}
    with patch("holidays.CL", return_value=fake_holidays):
        result = get_cycle_start_date(today=date(2026, 1, 5))
    assert result == date(2025, 12, 29)


def test_cycle_start_omite_feriado_y_fin_de_semana():
    """Feriado ficticio + fin de semana al final del mes se saltan correctamente.

    Escenario: en el mes de prueba los últimos días son:
      - dic 31 2025 (mié) = feriado → skip
      - dic 30 2025 (mar) = hábil → 1er hábil
      - dic 29 2025 (lun) = hábil → 2do hábil → inicio = dic 29

    Adicionalmente comprueba que un sábado previo también se saltaría.
    """
    fake_holidays = {date(2025, 12, 31): "Feriado ficticio"}
    with patch("holidays.CL", return_value=fake_holidays):
        result = get_cycle_start_date(today=date(2026, 1, 1))
    assert result == date(2025, 12, 29)


# ─────────────────────────────────────────────
# get_cycle_start_date: sin argumento usa fecha actual
# ─────────────────────────────────────────────

def test_cycle_start_sin_argumento_retorna_date():
    """Llamada sin argumentos no lanza excepción y retorna un date válido."""
    result = get_cycle_start_date()
    assert isinstance(result, date)
    # El resultado debe ser un día hábil (lunes–viernes)
    assert result.weekday() < 5, f"El ciclo inicia en fin de semana: {result}"
