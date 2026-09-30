"""Date, age and dose parsers (the dirtiest columns of the AEFI files)."""

from __future__ import annotations

import datetime as dt

import pytest

from vamengoc.parsing.ages import (
    age_group_from_months,
    normalize_age_group,
    parse_age,
    reconcile_age,
)
from vamengoc.parsing.dates import excel_serial_to_date, parse_date
from vamengoc.parsing.doses import parse_dose
from vamengoc.parsing.values import Status

D = dt.date


@pytest.mark.parametrize(
    ("value", "expected", "status"),
    [
        (dt.datetime(2017, 3, 4, 0, 0), D(2017, 3, 4), Status.OK),
        (D(2017, 3, 4), D(2017, 3, 4), Status.OK),
        ("04/03/2017", D(2017, 3, 4), Status.OK),
        ("4-3-17", D(2017, 3, 4), Status.OK),
        ("04.03.2017", D(2017, 3, 4), Status.OK),
        ("2017-03-04", D(2017, 3, 4), Status.OK),
        ("2017-03-04 00:00:00", D(2017, 3, 4), Status.OK),
        ("03/25/2017", D(2017, 3, 25), Status.RECOVERED),  # month-first only when day-first impossible
        ("42800", D(2017, 3, 6), Status.RECOVERED),  # serial number stored as text
        (42800, D(2017, 3, 6), Status.RECOVERED),  # 42736 = 2017-01-01
        (42800.0, D(2017, 3, 6), Status.RECOVERED),
        ("12 de enero de 2017", D(2017, 1, 12), Status.RECOVERED),
        ("12-ene-17", D(2017, 1, 12), Status.RECOVERED),
        ("N", None, Status.NOT_APPLICABLE),
        ("no procede", None, Status.NOT_APPLICABLE),
        ("", None, Status.MISSING),
        (None, None, Status.MISSING),
        (float("nan"), None, Status.MISSING),
        ("31/02/2017", None, Status.INVALID),
        ("mañana", None, Status.INVALID),
        (5, None, Status.INVALID),
        (True, None, Status.INVALID),
        ("99999", None, Status.INVALID),
        ("2017-02-30", None, Status.INVALID),
        ("40 de foo de 2017", None, Status.INVALID),
    ],
)
def test_parse_date(value: object, expected: dt.date | None, status: str) -> None:
    p = parse_date(value)
    assert (p.value, p.status) == (expected, status)


def test_two_digit_pivot() -> None:
    assert parse_date("01/01/29").value == D(2029, 1, 1)
    assert parse_date("01/01/31").value == D(1931, 1, 1)
    assert excel_serial_to_date(1) == D(1899, 12, 31)


@pytest.mark.parametrize(
    ("value", "months"),
    [
        ("6M", 6),
        ("18 m", 18),
        ("6 M", 6),
        ("6m", 6),
        ("6 MESES", 6),
        ("2A", 24),
        ("2 a", 24),
        ("2 AÑOS", 24),
        ("1A6M", 18),
        ("1 A 6 M", 18),
        ("RN", 0),
        ("R.N.", 0),
        ("recién nacido", 0),
        ("15 D", 15 / (365.25 / 12)),
        ("2 S", 14 / (365.25 / 12)),
        ("1,5A", 18),
        ("1.5 A", 18),
    ],
)
def test_parse_age(value: str, months: float) -> None:
    p = parse_age(value)
    assert p.status == Status.OK
    assert p.value == pytest.approx(months)


@pytest.mark.parametrize("value", ["6", "abc", "6X", "M6"])
def test_parse_age_invalid(value: str) -> None:
    assert parse_age(value).status == Status.INVALID


def test_parse_age_missing() -> None:
    assert parse_age(None).status == Status.MISSING


def test_reconcile_age() -> None:
    b, v = D(2017, 1, 1), D(2017, 4, 1)
    r = reconcile_age(3.0, b, v)
    assert r.source == "both_agree" and r.months == pytest.approx(90 / (365.25 / 12))
    r = reconcile_age(12.0, b, v)
    assert r.source == "conflict_derived"
    assert reconcile_age(None, b, v).source == "derived"
    assert reconcile_age(5.0, None, v).source == "reported"
    assert reconcile_age(None, None, None).source == "none"
    assert reconcile_age(5.0, D(2018, 1, 1), v).source == "reported"  # birth after vaccination
    # years are truncated in the reported field: 2A vs 2.5 years agrees
    assert reconcile_age(24.0, D(2014, 7, 1), D(2017, 1, 1)).source == "both_agree"


def test_age_groups() -> None:
    assert age_group_from_months(3) == "0-5"
    assert age_group_from_months(6 * 12) == "6-14"
    assert age_group_from_months(15 * 12) == "15-60"
    assert age_group_from_months(70 * 12) == "61+"
    assert age_group_from_months(None) is None
    assert age_group_from_months(-1) is None
    assert normalize_age_group("0 a 5") == "0-5"
    assert normalize_age_group("61 y +") == "61+"
    assert normalize_age_group("0-5") == "0-5"
    assert normalize_age_group("6 a 14") == "6-14"
    assert normalize_age_group("") is None
    assert normalize_age_group("adultos") is None


@pytest.mark.parametrize(
    ("value", "doses", "status"),
    [
        ("1", ("1",), Status.OK),
        (2, ("2",), Status.OK),
        (3.0, ("3",), Status.OK),
        ("R", ("R",), Status.OK),
        ("u", ("U",), Status.OK),
        ("1ra", ("1",), Status.OK),
        ("Refuerzo", ("R",), Status.OK),
        ("1,R", ("1", "R"), Status.OK),
        ("2 y 1", ("2", "1"), Status.OK),
        ("2,1", ("2", "1"), Status.OK),
        (2.1, ("2", "1"), Status.RECOVERED),
        ("2.1", ("2", "1"), Status.RECOVERED),
        (3.1, ("3", "1"), Status.RECOVERED),
        (1.2, ("1", "2"), Status.RECOVERED),
        (0.5, ("1", "2"), Status.RECOVERED),
        (dt.datetime(2017, 2, 1), ("1", "2"), Status.RECOVERED),
        (None, None, Status.MISSING),
        ("", None, Status.MISSING),
        ("X", None, Status.INVALID),
        (9, None, Status.INVALID),
        (dt.datetime(2017, 12, 25), None, Status.INVALID),
        (True, None, Status.INVALID),
        (float("nan"), None, Status.MISSING),
        ("10.5", None, Status.INVALID),
        ("1/2", ("1", "2"), Status.OK),
    ],
)
def test_parse_dose(value: object, doses: tuple[str, ...] | None, status: str) -> None:
    p = parse_dose(value)
    assert (p.value, p.status) == (doses, status)
