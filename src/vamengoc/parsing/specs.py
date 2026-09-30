"""Parsing of acceptance criteria written as text in the lot-release workbook.

The specification row carries strings such as ``"≥ 80 %"``, ``"(70 -130) μg/mL"``,
``"≤ 20000 UE/mL"``, ``"6,0 - 7,2"`` or a qualitative description. They are
parsed into numeric limits so that conformance and the position of each lot
inside its specification window can be computed rather than read.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from vamengoc.parsing.text import cell_to_str, strip_accents

__all__ = ["Spec", "parse_spec"]

Op = Literal["range", "ge", "gt", "le", "lt", "qualitative"]

_NUM = r"[+-]?\d+(?:[.,]\d+)?(?:\s?\d{3})*(?:[.,]\d+)?"
_RANGE = re.compile(rf"(?P<a>{_NUM})\s*(?:-|–|—|a|al|hasta|y|to)\s*(?P<b>{_NUM})", re.IGNORECASE)
_GE = re.compile(
    rf"(?:≥|>=|=>|mayor\s+o\s+igual(?:\s+(?:que|a))?|minimo|no\s+menor\s+de|min\.?)\s*(?P<a>{_NUM})", re.IGNORECASE
)
_GT = re.compile(rf"(?:>|mayor\s+(?:que|de))\s*(?P<a>{_NUM})", re.IGNORECASE)
_LE = re.compile(
    rf"(?:≤|<=|=<|menor\s+o\s+igual(?:\s+(?:que|a))?|maximo|no\s+mayor\s+de|max\.?)\s*(?P<a>{_NUM})", re.IGNORECASE
)
_LT = re.compile(rf"(?:<|menor\s+(?:que|de))\s*(?P<a>{_NUM})", re.IGNORECASE)
_UNIT = re.compile(r"(%|[µμu]g\s*/\s*m[lL]|mg\s*/\s*m[lL]|U[EI]\s*/\s*m[lL]|EU\s*/\s*m[lL]|UIgG\s*/\s*m[lL]|m[lL])")


def _num(s: str) -> float:
    t = s.replace(" ", "")
    if "," in t and "." not in t:
        t = t.replace(",", ".")
    elif "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    return float(t)


@dataclass(frozen=True, slots=True)
class Spec:
    """Acceptance criterion. ``low``/``high`` are ``None`` when unbounded."""

    op: Op
    low: float | None = None
    high: float | None = None
    unit: str = ""
    raw: str = ""

    @property
    def is_quantitative(self) -> bool:
        return self.op != "qualitative"

    def conforms(self, x: float | None) -> bool | None:
        """Whether a value meets the criterion (``None`` for missing values)."""
        if x is None or (isinstance(x, float) and math.isnan(x)) or not self.is_quantitative:
            return None
        if self.op == "range":
            assert self.low is not None
            assert self.high is not None
            return self.low <= x <= self.high
        if self.op == "ge":
            assert self.low is not None
            return x >= self.low
        if self.op == "gt":
            assert self.low is not None
            return x > self.low
        if self.op == "le":
            assert self.high is not None
            return x <= self.high
        assert self.high is not None
        return x < self.high

    def as_dict(self) -> dict[str, Any]:
        return {"op": self.op, "low": self.low, "high": self.high, "unit": self.unit, "raw": self.raw}

    def matches(self, other: Spec, rel_tol: float = 1e-9) -> bool:
        """Numeric equality of two criteria (used to report specification drift)."""

        def close(a: float | None, b: float | None) -> bool:
            if a is None or b is None:
                return a is b
            return math.isclose(a, b, rel_tol=rel_tol, abs_tol=1e-12)

        same_op = self.op == other.op or {self.op, other.op} <= {"ge", "gt"} or {self.op, other.op} <= {"le", "lt"}
        return same_op and close(self.low, other.low) and close(self.high, other.high)


def parse_spec(value: Any) -> Spec:
    """Parse one specification cell. Unparseable text becomes a qualitative spec."""
    raw = cell_to_str(value) or ""
    text = strip_accents(raw).replace(" ", " ").strip()
    unit_m = _UNIT.search(raw)
    unit = unit_m.group(1).replace(" ", "") if unit_m else ""
    unit = unit.replace("μ", "µ").replace("u", "µ") if unit.lower().startswith(("μg", "ug", "µg")) else unit
    for pattern, op in ((_GE, "ge"), (_LE, "le"), (_GT, "gt"), (_LT, "lt")):
        m = pattern.search(text)
        if m:
            v = _num(m.group("a"))
            if op in ("ge", "gt"):
                return Spec(op=op, low=v, unit=unit, raw=raw)  # type: ignore[arg-type]
            return Spec(op=op, high=v, unit=unit, raw=raw)  # type: ignore[arg-type]
    m = _RANGE.search(text)
    if m:
        a, b = _num(m.group("a")), _num(m.group("b"))
        if a > b:
            a, b = b, a
        return Spec(op="range", low=a, high=b, unit=unit, raw=raw)
    return Spec(op="qualitative", unit="", raw=raw)
