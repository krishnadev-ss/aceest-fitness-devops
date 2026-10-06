"""Unit tests for the pure business logic (no HTTP involved)."""
import pytest

from app import (PROGRAMS, ValidationError, calculate_bmi,
                 calculate_calories, get_program, validate_adherence,
                 validate_client)


@pytest.mark.parametrize("code, weight, expected", [
    ("FL", 70, 1540),
    ("MG", 80, 2800),
    ("BG", 60.5, 1573),
])
def test_calculate_calories(code, weight, expected):
    assert calculate_calories(weight, code) == expected


def test_program_lookup_is_case_insensitive():
    assert get_program(" mg ")[0] == "MG"


def test_unknown_program_rejected():
    with pytest.raises(ValidationError, match="unknown program"):
        calculate_calories(70, "XX")


@pytest.mark.parametrize("weight", [0, -5, "70", None, True])
def test_invalid_weight_rejected(weight):
    with pytest.raises(ValidationError):
        calculate_calories(weight, "FL")


@pytest.mark.parametrize("weight, height, bmi, category", [
    (50, 180, 15.4, "Underweight"),
    (70, 175, 22.9, "Normal"),
    (85, 175, 27.8, "Overweight"),
    (110, 175, 35.9, "Obese"),
])
def test_calculate_bmi(weight, height, bmi, category):
    assert calculate_bmi(weight, height) == (bmi, category)


def test_bmi_rejects_zero_height():
    with pytest.raises(ValidationError):
        calculate_bmi(70, 0)


def test_every_program_is_complete():
    for program in PROGRAMS.values():
        assert program["workout"] and program["diet"]
        assert program["calorie_factor"] > 0


def test_validate_client_normalises_and_computes_calories():
    result = validate_client(
        {"name": "  Asha ", "age": 30, "weight_kg": 60, "program": "fl"}
    )
    assert result == {"name": "Asha", "age": 30, "weight_kg": 60.0,
                      "program": "FL", "calories": 1320}


@pytest.mark.parametrize("patch", [
    {"name": ""}, {"age": 5}, {"age": "30"}, {"program": "ZZ"},
    {"weight_kg": -1},
])
def test_validate_client_rejects_bad_fields(patch):
    payload = {"name": "Asha", "age": 30, "weight_kg": 60, "program": "FL"}
    with pytest.raises(ValidationError):
        validate_client({**payload, **patch})


@pytest.mark.parametrize("value", [-1, 101, 50.5, "80", None])
def test_validate_adherence_rejects_out_of_range(value):
    with pytest.raises(ValidationError):
        validate_adherence(value)
