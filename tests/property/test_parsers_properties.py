"""Property-based tests: parsers never crash and respect their contracts on arbitrary input."""

from __future__ import annotations

import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from vamengoc.parsing.ages import parse_age
from vamengoc.parsing.dates import parse_date
from vamengoc.parsing.doses import VALID_DOSES, parse_dose
from vamengoc.parsing.lots import core_key, exact_key, parse_lots
from vamengoc.parsing.specs import parse_spec
from vamengoc.parsing.text import compact, normalize_text
from vamengoc.parsing.values import Status, parse_number, parse_sex, parse_yes_no

STATUSES = {Status.OK, Status.MISSING, Status.NOT_APPLICABLE, Status.INVALID, Status.RECOVERED}
cells = st.one_of(
    st.none(),
    st.text(max_size=40),
    st.integers(-(10**9), 10**9),
    st.floats(allow_nan=True, allow_infinity=True),
    st.booleans(),
    st.dates(min_value=dt.date(1900, 1, 1), max_value=dt.date(2100, 1, 1)),
    st.datetimes(min_value=dt.datetime(1900, 1, 1), max_value=dt.datetime(2100, 1, 1)),
)


@settings(max_examples=400, deadline=None)
@given(cells)
def test_parsers_total(value: object) -> None:
    for parser in (parse_date, parse_age, parse_dose, parse_lots, parse_number, parse_sex, parse_yes_no):
        p = parser(value)
        assert p.status in STATUSES
        if p.status in (Status.MISSING, Status.INVALID, Status.NOT_APPLICABLE):
            assert p.value is None
    parse_spec(value)


@given(st.text(max_size=40))
def test_normalisation_idempotent(s: str) -> None:
    n = normalize_text(s)
    assert normalize_text(n) == n
    assert " " not in compact(s)
    assert n == n.strip() and "  " not in n


@given(st.dates(min_value=dt.date(1931, 1, 1), max_value=dt.date(2029, 12, 31)))
def test_date_roundtrip_dayfirst(d: dt.date) -> None:
    assert parse_date(d.strftime("%d/%m/%Y")).value == d
    assert parse_date(d.isoformat()).value == d
    assert parse_date(d.strftime("%d/%m/%y")).value == d


@given(st.integers(0, 110 * 12))
def test_age_months_and_years(m: int) -> None:
    assert parse_age(f"{m}M").value == m
    assert parse_age(f"{m // 12}A").value == (m // 12) * 12


@given(st.lists(st.sampled_from(VALID_DOSES), min_size=1, max_size=3))
def test_dose_lists(doses: list[str]) -> None:
    p = parse_dose(",".join(doses))
    assert p.value == tuple(doses)


@given(st.integers(1, 99999), st.sampled_from(["M", "X", "MX", ""]))
def test_lot_keys(num: int, letters: str) -> None:
    a = f"{num}{letters}"
    assert exact_key(f" {a.lower()} ") == a
    if letters:
        assert core_key(f"{letters}{num}") == core_key(a) or len(letters) > 1
    p = parse_lots(a)
    assert p.value is not None and p.value[0].exact == a


@given(st.floats(0.01, 1e6, allow_nan=False), st.floats(0.01, 1e6, allow_nan=False))
def test_spec_ranges(a: float, b: float) -> None:
    s = parse_spec(f"{a:.2f} - {b:.2f}")
    assert s.op == "range" and s.low is not None and s.high is not None and s.low <= s.high
