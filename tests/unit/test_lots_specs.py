"""Lot identifiers and specification parsing."""

from __future__ import annotations

import datetime as dt

import pytest

from vamengoc.parsing.lots import core_key, exact_key, parse_lots
from vamengoc.parsing.specs import Spec, parse_spec
from vamengoc.parsing.values import Status


@pytest.mark.parametrize(
    ("raw", "exact", "core"),
    [
        ("575M", "575M", "575:M"),
        ("M575", "M575", "575:M"),
        ("M 575", "M575", "575:M"),
        ("575 m", "575M", "575:M"),
        ("575-M", "575M", "575:M"),
        ("575MX", "575MX", "575:MX"),
        ("0575M", "0575M", "575:M"),
        ("A12B34", "A12B34", None),
    ],
)
def test_keys(raw: str, exact: str, core: str | None) -> None:
    assert exact_key(raw) == exact
    assert core_key(raw) == core


def test_parse_lots_variants() -> None:
    p = parse_lots("575M, 1234")
    assert p.status == Status.OK
    assert [k.exact for k in p.value] == ["575M", "1234"]
    assert parse_lots(575).value[0].exact == "575"
    assert parse_lots(575.0).value[0].exact == "575"
    assert parse_lots("Lote: 575M").value[0].exact == "575M"
    assert parse_lots("No. 575M").value[0].exact == "575M"
    assert parse_lots("575M y 576M").value[1].exact == "576M"
    assert parse_lots("575M/576M").value[1].exact == "576M"


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        (None, Status.MISSING),
        ("", Status.MISSING),
        ("-", Status.MISSING),
        (dt.datetime(2017, 5, 7), Status.INVALID),
        ("2017-05-07 00:00:00", Status.INVALID),
        ("sin lote", Status.INVALID),
    ],
)
def test_parse_lots_bad(raw: object, status: str) -> None:
    assert parse_lots(raw).status == status


@pytest.mark.parametrize(
    ("text", "op", "low", "high"),
    [
        ("≥ 80 %", "ge", 80, None),
        (">= 80", "ge", 80, None),
        ("(70 -130) μg/mL", "range", 70, 130),
        ("≤ 20000 UE/mL", "le", None, 20000),
        ("6,0 - 7,2", "range", 6.0, 7.2),
        ("> 4", "gt", 4, None),
        ("≥ 7000 UIgG/mL", "ge", 7000, None),
        ("(3 - 5) mg/mL", "range", 3, 5),
        ("(0,07 - 0,13) mg/mL", "range", 0.07, 0.13),
        ("≥ 0,5 mL", "ge", 0.5, None),
        ("< 1", "lt", None, 1),
        ("entre 70 y 130", "range", 70, 130),
        ("130 - 70", "range", 70, 130),
        ("mínimo 80", "ge", 80, None),
        ("no mayor de 20 000", "le", None, 20000),
    ],
)
def test_parse_spec(text: str, op: str, low: float | None, high: float | None) -> None:
    s = parse_spec(text)
    assert s.op == op
    assert (s.low, s.high) == (
        pytest.approx(low) if low is not None else None,
        pytest.approx(high) if high is not None else None,
    )


def test_spec_units_and_qualitative() -> None:
    assert parse_spec("(70 -130) μg/mL").unit == "µg/mL"
    assert parse_spec("(70 -130) ug/mL").unit == "µg/mL"
    q = parse_spec("Suspensión blanco opalescente")
    assert q.op == "qualitative" and not q.is_quantitative and q.conforms(1.0) is None
    assert parse_spec(None).op == "qualitative"


def test_conformance() -> None:
    r = Spec("range", 70, 130)
    assert r.conforms(70) and r.conforms(130) and not r.conforms(69.9)
    assert Spec("ge", 80).conforms(80) and not Spec("ge", 80).conforms(79)
    assert Spec("gt", 4).conforms(8) and not Spec("gt", 4).conforms(4)
    assert Spec("le", high=20000).conforms(20000) and not Spec("le", high=20000).conforms(20001)
    assert Spec("lt", high=1).conforms(0.5) and not Spec("lt", high=1).conforms(1)
    assert r.conforms(None) is None and r.conforms(float("nan")) is None


def test_spec_matching() -> None:
    assert Spec("ge", 80).matches(Spec("gt", 80))
    assert Spec("range", 70, 130).matches(Spec("range", 70.0, 130.0))
    assert not Spec("range", 70, 130).matches(Spec("range", 60, 130))
    assert not Spec("le", high=5).matches(Spec("ge", 5))
    assert Spec("range", 6, 7.2).as_dict()["op"] == "range"
