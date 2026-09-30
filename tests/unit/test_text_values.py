"""Text normalisation and scalar parsers."""

from __future__ import annotations

import datetime as dt
import math

import pytest

from vamengoc.parsing.text import cell_to_str, compact, is_missing, normalize_text, strip_accents
from vamengoc.parsing.values import Status, parse_integer, parse_number, parse_sex, parse_yes_no


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (float("nan"), None),
        (575, "575"),
        (575.0, "575"),
        (0.5, "0.5"),
        (True, "S"),
        (False, "N"),
        ("  M, ", "M,"),
        ("a b", "a b"),
        (dt.datetime(2017, 1, 2), "2017-01-02"),
        (dt.datetime(2017, 1, 2, 10, 30), "2017-01-02 10:30:00"),
        (dt.date(2020, 5, 1), "2020-05-01"),
        ("nan", None),
        ("NaT", None),
    ],
)
def test_cell_to_str(value: object, expected: str | None) -> None:
    assert cell_to_str(value) == expected


def test_normalize_and_compact() -> None:
    assert strip_accents("Camagüey Ñandú áéíóú") == "Camaguey Nandu aeiou"
    assert normalize_text("  Heber- biotec ") == "HEBER BIOTEC"
    assert compact("R.L.S") == compact("RLS") == "RLS"
    assert normalize_text(575.0) == normalize_text("575") == "575"
    assert normalize_text(None) == ""
    assert normalize_text([1, 2]) == "1 2"  # unhashable input bypasses the cache
    # the memoisation must distinguish True (bool) from 1 (int)
    assert normalize_text(True) == "S"
    assert normalize_text(1) == "1"


@pytest.mark.parametrize("value", ["", "-", "  ", None, "S/D", "sin datos", "N/A", "nan"])
def test_is_missing(value: object) -> None:
    assert is_missing(value)


@pytest.mark.parametrize(
    ("value", "expected", "status"),
    [
        ("S", True, Status.OK),
        ("s", True, Status.OK),
        (" S ", True, Status.OK),
        ("Si", True, Status.OK),
        ("N ", False, Status.OK),
        ("        N", False, Status.OK),
        ("n", False, Status.OK),
        ("NO", False, Status.OK),
        ("SS", True, Status.RECOVERED),
        ("NN", False, Status.RECOVERED),
        (None, None, Status.MISSING),
        ("", None, Status.MISSING),
        ("quizas", None, Status.INVALID),
        (1, True, Status.OK),
        (0, False, Status.OK),
    ],
)
def test_yes_no(value: object, expected: bool | None, status: str) -> None:
    p = parse_yes_no(value)
    assert p.value is expected
    assert p.status == status


@pytest.mark.parametrize(
    ("value", "expected", "status"),
    [
        ("M", "M", Status.OK),
        ("m", "M", Status.OK),
        ("F ", "F", Status.OK),
        ("M,", "M", Status.OK),
        ("Femenino", "F", Status.OK),
        ("masculino", "M", Status.OK),
        (None, None, Status.MISSING),
        ("X", None, Status.INVALID),
    ],
)
def test_sex(value: object, expected: str | None, status: str) -> None:
    p = parse_sex(value)
    assert (p.value, p.status) == (expected, status)


@pytest.mark.parametrize(
    ("value", "expected", "status"),
    [
        (12, 12.0, Status.OK),
        (12.5, 12.5, Status.OK),
        ("12,5", 12.5, Status.RECOVERED),
        ("1.234,5", 1234.5, Status.RECOVERED),
        ("1,234.5", 1234.5, Status.RECOVERED),
        ("20 000", 20000.0, Status.OK),
        ("1,234,567", 1234567.0, Status.RECOVERED),
        ("1.234.567", 1234567.0, Status.RECOVERED),
        ("-", None, Status.MISSING),
        ("abc", None, Status.INVALID),
        (float("nan"), None, Status.MISSING),
        (float("inf"), None, Status.INVALID),
        (True, None, Status.INVALID),
        ("1e3", 1000.0, Status.OK),
        ("≤ 5", None, Status.INVALID),
    ],
)
def test_number(value: object, expected: float | None, status: str) -> None:
    p = parse_number(value)
    assert p.status == status
    if expected is None:
        assert p.value is None
    else:
        assert p.value is not None and math.isclose(p.value, expected)


def test_integer() -> None:
    assert parse_integer("2017").value == 2017
    assert parse_integer(2017.0).value == 2017
    assert parse_integer("2017.5").status == Status.INVALID
    assert parse_integer(None).status == Status.MISSING
