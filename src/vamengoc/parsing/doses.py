"""Dose-number parsing.

The ``Dosis`` column mixes clean values (1, 2, 3, R, U) with artefacts of
co-administration typed into a single cell and then mangled by the
spreadsheet: ``"1,R"``, ``"2 y 1"``, the decimal ``2.1`` (two doses written
``2,1`` and read as a Spanish decimal), the fraction ``0.5`` (``1/2`` read as a
fraction) and even a date (``1/2`` read as 1 February). Each repair rule is
explicit and reported with status ``recovered``.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from fractions import Fraction
from typing import Any

from vamengoc.parsing.text import MISSING_TOKENS, cell_to_str, normalize_text, strip_accents
from vamengoc.parsing.values import Parsed, Status

__all__ = ["VALID_DOSES", "parse_dose"]

VALID_DOSES = ("1", "2", "3", "4", "5", "R", "U")
_WORDS = {
    "PRIMERA": "1",
    "SEGUNDA": "2",
    "TERCERA": "3",
    "CUARTA": "4",
    "QUINTA": "5",
    "REFUERZO": "R",
    "REF": "R",
    "REACTIVACION": "R",
    "R1": "R",
    "R2": "R",
    "UNICA": "U",
    "UNICO": "U",
    "DOSISUNICA": "U",
}
_ORDINAL = re.compile(r"^(\d)(?:RA|DA|TA|RO|DO|TO|MA|NA|A|O|ª|º)?$")
_SPLIT = re.compile(r"\s*(?:,|;|/|\+|-|&|\s+Y\s+|\s+)\s*")
_MAX_DOSE = 5


def _token(tok: str) -> str | None:
    t = tok.strip().upper()
    if not t:
        return None
    if t in VALID_DOSES:
        return t
    if t in _WORDS:
        return _WORDS[t]
    m = _ORDINAL.match(t)
    if m and 1 <= int(m.group(1)) <= _MAX_DOSE:
        return m.group(1)
    return None


def _from_float(x: float) -> tuple[list[str] | None, str]:
    """Repair a number that should have been a dose (or a pair of doses)."""
    if x.is_integer() and 1 <= int(x) <= _MAX_DOSE:
        return [str(int(x))], Status.OK
    text = repr(x)
    m = re.fullmatch(r"([1-5])\.([1-5]|R)", text)
    if m:  # "2,1" typed in a Spanish-locale sheet and stored as the decimal 2.1
        return [m.group(1), m.group(2)], Status.RECOVERED
    if 0 < x < 1:  # "1/2" interpreted as a fraction
        frac = Fraction(x).limit_denominator(_MAX_DOSE)
        if abs(float(frac) - x) < 1e-9 and 1 <= frac.numerator <= _MAX_DOSE:
            return [str(frac.numerator), str(frac.denominator)], Status.RECOVERED
    return None, Status.INVALID


def parse_dose(value: Any) -> Parsed[tuple[str, ...]]:
    """Return the tuple of dose tokens written in a cell (one per co-administered vaccine)."""
    if value is None:
        return Parsed(None, Status.MISSING)
    if isinstance(value, dt.datetime | dt.date):
        # "1/2" auto-converted to a date: day-first locale → (day, month).
        day, month = value.day, value.month
        if 1 <= day <= _MAX_DOSE and 1 <= month <= _MAX_DOSE:
            return Parsed((str(day), str(month)), Status.RECOVERED)
        return Parsed(None, Status.INVALID)
    if isinstance(value, bool):
        return Parsed(None, Status.INVALID)
    if isinstance(value, int | float):
        if math.isnan(float(value)):
            return Parsed(None, Status.MISSING)
        doses, status = _from_float(float(value))
        return Parsed(tuple(doses), status) if doses else Parsed(None, status)

    text = cell_to_str(value) or ""
    if normalize_text(text) in MISSING_TOKENS:
        return Parsed(None, Status.MISSING)
    text = strip_accents(text).upper().strip()
    single = _token(text.replace(" ", ""))
    if single:
        return Parsed((single,), Status.OK)
    # A numeric string such as "2.1" or "0.5" follows the float repair rules.
    if re.fullmatch(r"\d+[.,]\d+", text):
        doses, status = _from_float(float(text.replace(",", ".")))
        if doses:
            # "2,1" written with a comma is an explicit list, not a repair.
            return Parsed(tuple(doses), Status.OK if "," in text else status)
        return Parsed(None, status)
    parts = [p for p in _SPLIT.split(text) if p]
    tokens = [_token(p) for p in parts]
    if tokens and all(t is not None for t in tokens):
        return Parsed(tuple(t for t in tokens if t is not None), Status.OK)
    return Parsed(None, Status.INVALID)
