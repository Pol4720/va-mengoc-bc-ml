"""Scalar parsers for indicator, sex, integer and numeric cells.

Every parser returns a ``Parsed`` pair ``(value, status)``. The status feeds
the automatic data-quality report, so a parser never silently coerces: a value
it cannot interpret is returned as missing with status ``"invalid"``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from vamengoc.parsing.text import (
    MISSING_TOKENS,
    NOT_APPLICABLE_TOKENS,
    cell_to_str,
    normalize_text,
)

__all__ = [
    "Parsed",
    "Status",
    "parse_integer",
    "parse_number",
    "parse_sex",
    "parse_yes_no",
]

T = TypeVar("T")


class Status:
    OK = "ok"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    INVALID = "invalid"
    RECOVERED = "recovered"  # interpretable only after a documented repair rule


@dataclass(frozen=True, slots=True)
class Parsed(Generic[T]):
    value: T | None
    status: str


_YES = frozenset({"S", "SI", "Y", "YES", "1", "X", "POSITIVO", "VERDADERO", "TRUE"})
_NO = frozenset({"N", "NO", "0", "NEGATIVO", "FALSO", "FALSE"})


def parse_yes_no(value: Any) -> Parsed[bool]:
    """S/N indicator → nullable bool. Blank is *unknown*, never assumed 'N'."""
    token = normalize_text(value)
    if token in _YES:
        return Parsed(True, Status.OK)
    if token in _NO:
        return Parsed(False, Status.OK)
    if token in MISSING_TOKENS:
        return Parsed(None, Status.MISSING)
    # Repeated letters ("SS", "NN") or a trailing comma artefact already stripped.
    if token and set(token.replace(" ", "")) == {"S"}:
        return Parsed(True, Status.RECOVERED)
    if token and set(token.replace(" ", "")) == {"N"}:
        return Parsed(False, Status.RECOVERED)
    return Parsed(None, Status.INVALID)


_MALE = frozenset({"M", "MASCULINO", "MASC", "H", "HOMBRE", "VARON", "MALE"})
_FEMALE = frozenset({"F", "FEMENINO", "FEM", "MUJER", "HEMBRA", "FEMALE"})


def parse_sex(value: Any) -> Parsed[str]:
    """Sex → 'M' / 'F'. Tolerates case, spacing and stray punctuation ('M,', 'F ')."""
    token = normalize_text(value).replace(" ", "")
    if token in _MALE:
        return Parsed("M", Status.OK)
    if token in _FEMALE:
        return Parsed("F", Status.OK)
    if token in {t.replace(" ", "") for t in MISSING_TOKENS}:
        return Parsed(None, Status.MISSING)
    return Parsed(None, Status.INVALID)


_NUM_CLEAN = re.compile(r"[\s   ]")
_NUM_OK = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")


def parse_number(value: Any) -> Parsed[float]:
    """Numeric cell → float, handling Spanish decimal commas and thousands marks.

    Rules (documented because they are a data transformation):

    * native int/float cells are used as is;
    * ``"12,5"`` → 12.5 (a single comma is a decimal separator — Spanish locale),
      reported with status ``recovered``;
    * ``"1.234,5"`` → 1234.5 and ``"1,234.5"`` → 1234.5 (the last separator is the
      decimal mark when both appear);
    * ``"20 000"`` → 20000 (spaces are thousands separators);
    * anything else (units, operators, text) → invalid.
    """
    if isinstance(value, bool):
        return Parsed(None, Status.INVALID)
    if isinstance(value, int | float):
        f = float(value)
        if math.isnan(f):
            return Parsed(None, Status.MISSING)
        if math.isinf(f):
            return Parsed(None, Status.INVALID)
        return Parsed(f, Status.OK)
    s = cell_to_str(value)
    if s is None or normalize_text(s) in MISSING_TOKENS:
        return Parsed(None, Status.MISSING)
    s = _NUM_CLEAN.sub("", s)
    status = Status.OK
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        status = Status.RECOVERED
    elif s.count(",") == 1:
        s = s.replace(",", ".")
        status = Status.RECOVERED
    elif s.count(",") > 1:
        s = s.replace(",", "")
        status = Status.RECOVERED
    elif s.count(".") > 1:
        s = s.replace(".", "")
        status = Status.RECOVERED
    if not _NUM_OK.match(s):
        return Parsed(None, Status.INVALID)
    f = float(s)
    if math.isinf(f) or math.isnan(f):
        return Parsed(None, Status.INVALID)
    return Parsed(f, status)


def parse_integer(value: Any) -> Parsed[int]:
    """Integer cell (years, months, counts). Non-integral numbers are invalid."""
    num = parse_number(value)
    if num.value is None:
        return Parsed(None, num.status)
    if not float(num.value).is_integer():
        return Parsed(None, Status.INVALID)
    return Parsed(int(num.value), num.status)


def is_not_applicable(value: Any) -> bool:
    """True for the 'N' / 'no procede' codes used as 'not applicable' in date columns."""
    return normalize_text(value) in NOT_APPLICABLE_TOKENS
