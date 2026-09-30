"""Age parsing and reconciliation.

``EDAD`` is free text: a number followed by a unit (``M`` months, ``A`` years,
``D`` days, ``S`` weeks), with or without spaces and in any case, plus ``RN``
(newborn). Combined forms such as ``1A6M`` are accepted. The reported age is
reconciled with the age derived from birth and vaccination dates.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from vamengoc.parsing.text import MISSING_TOKENS, cell_to_str, normalize_text, strip_accents
from vamengoc.parsing.values import Parsed, Status, parse_number

__all__ = [
    "AGE_GROUPS",
    "DAYS_PER_MONTH",
    "ReconciledAge",
    "age_group_from_months",
    "months_between",
    "normalize_age_group",
    "parse_age",
    "reconcile_age",
]

DAYS_PER_MONTH = 365.25 / 12

_UNIT_MONTHS = {
    "A": 12.0,
    "ANO": 12.0,
    "ANOS": 12.0,
    "AN": 12.0,
    "Y": 12.0,
    "YEARS": 12.0,
    "M": 1.0,
    "MES": 1.0,
    "MESES": 1.0,
    "MS": 1.0,
    "D": 1.0 / DAYS_PER_MONTH,
    "DIA": 1.0 / DAYS_PER_MONTH,
    "DIAS": 1.0 / DAYS_PER_MONTH,
    "S": 7.0 / DAYS_PER_MONTH,
    "SEM": 7.0 / DAYS_PER_MONTH,
    "SEMANA": 7.0 / DAYS_PER_MONTH,
    "SEMANAS": 7.0 / DAYS_PER_MONTH,
}
_PART = re.compile(r"(\d+(?:#\d+)?)([A-Z]+)")
_DECIMAL = re.compile(r"(?<=\d)[.,](?=\d)")
_NOISE = re.compile(r"[^0-9A-Z#]+")
_NEWBORN = frozenset({"RN", "RECIENNACIDO", "NEONATO"})

# Programme age groups as used by the surveillance system.
AGE_GROUPS: tuple[tuple[str, float, float], ...] = (
    ("0-5", 0.0, 6 * 12.0),
    ("6-14", 6 * 12.0, 15 * 12.0),
    ("15-60", 15 * 12.0, 61 * 12.0),
    ("61+", 61 * 12.0, float("inf")),
)


def parse_age(value: Any) -> Parsed[float]:
    """Return the reported age in months.

    A bare number without unit is ambiguous and is returned as missing with
    status ``invalid`` — it is resolved later from dates when possible.
    """
    if normalize_text(value) in MISSING_TOKENS:
        return Parsed(None, Status.MISSING)
    raw = cell_to_str(value) or ""
    # Protect decimal separators, then drop spaces/punctuation: "1,5 A" -> "1#5A".
    compacted = _NOISE.sub("", _DECIMAL.sub("#", strip_accents(raw).upper()))
    if compacted in _NEWBORN:
        return Parsed(0.0, Status.OK)
    parts = _PART.findall(compacted)
    if not parts or "".join(n + u for n, u in parts) != compacted:
        return Parsed(None, Status.INVALID)
    total = 0.0
    for number, unit in parts:
        if unit not in _UNIT_MONTHS:
            return Parsed(None, Status.INVALID)
        n = parse_number(number.replace("#", ".")).value
        if n is None:
            return Parsed(None, Status.INVALID)
        total += n * _UNIT_MONTHS[unit]
    return Parsed(total, Status.OK)


def months_between(start: dt.date, end: dt.date) -> float:
    """Exact elapsed time in (average-length) months."""
    return (end - start).days / DAYS_PER_MONTH


@dataclass(frozen=True, slots=True)
class ReconciledAge:
    months: float | None
    source: str  # both_agree | derived | reported | conflict_derived | none
    discrepancy_months: float | None


def reconcile_age(
    reported_months: float | None,
    birth_date: dt.date | None,
    vaccination_date: dt.date | None,
    *,
    tolerance_months: float = 2.0,
    max_age_years: float = 110.0,
) -> ReconciledAge:
    """Combine the reported age with the date-derived age.

    The date-derived age wins when it is plausible (0 ≤ age ≤ max) because it is
    computed rather than transcribed; disagreements beyond the tolerance are
    flagged ``conflict_derived`` for the data-quality report.
    """
    derived: float | None = None
    if birth_date is not None and vaccination_date is not None:
        d = months_between(birth_date, vaccination_date)
        if 0 <= d <= max_age_years * 12:
            derived = d
    if derived is not None and reported_months is not None:
        diff = abs(derived - reported_months)
        # Reported ages are truncated to whole units: allow a year's truncation for "A".
        src = "both_agree" if diff <= max(tolerance_months, 0.0) else "conflict_derived"
        # Ages reported in whole years are truncated: "2A" covers 24 <= age < 36 months.
        if src == "conflict_derived" and reported_months >= 12 and reported_months <= derived < reported_months + 12:
            src = "both_agree"
        return ReconciledAge(derived, src, diff)
    if derived is not None:
        return ReconciledAge(derived, "derived", None)
    if reported_months is not None and 0 <= reported_months <= max_age_years * 12:
        return ReconciledAge(reported_months, "reported", None)
    return ReconciledAge(None, "none", None)


def age_group_from_months(months: float | None) -> str | None:
    """Map an age in months to the programme age group."""
    if months is None:
        return None
    for label, lo, hi in AGE_GROUPS:
        if lo <= months < hi:
            return label
    return None


_GROUP = re.compile(r"^(\d+)\s*(?:A|AL|HASTA|\s)\s*(\d+)$")


def normalize_age_group(value: Any) -> str | None:
    """'0 a 5' → '0-5', '61 y +' → '61+'; unknown shapes → None."""
    token = normalize_text(value)
    if token in MISSING_TOKENS:
        return None
    m = _GROUP.match(token)
    if m:
        return f"{int(m.group(1))}-{int(m.group(2))}"
    m = re.match(r"^(\d+)\s*(?:Y|O)?\s*(?:MAS|\+)?$", token)
    if m and ("Y" in token or "MAS" in token or str(value).strip().endswith("+")):
        return f"{int(m.group(1))}+"
    return None
