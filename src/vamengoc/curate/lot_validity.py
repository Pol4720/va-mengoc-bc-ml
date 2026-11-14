"""Validity of the lot recorded in a VA-MENGOC-BC report.

The lot code carries its release year: the first digit of the identifier is the last digit of
the year in which the lot was released (a lot of 2011 starts with 1, as does one of 2001), and
a lot is valid for three years. Combined with the vaccination date this gives the decade
without ambiguity: the release year is the latest year not after the vaccination whose last
digit is the code digit. A lot is

* ``valid``          when ``release <= vaccination year <= release + shelf life``;
* ``expired``        when the vaccination is later than the end of the shelf life;
* ``before_release`` when the vaccination precedes the release year (possible only when the
  release year comes from the lots workbook rather than from the code).

An expired or not-yet-released lot cannot have been administered: the LOTE cell was copied
from another row and not updated. These reports keep their place in Paper 1 (the lot is not
used there) but cannot support a lot-level analysis (Paper 2). Errors that stay inside the
validity window are undetectable, so the observed share is a lower bound of the error rate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

__all__ = [
    "CODE_RULES",
    "CodeRuleCheck",
    "check_code_rules",
    "code_digits",
    "lot_status",
    "release_year_from_code",
    "rule_table",
]

_DIGITS = re.compile(r"\d+")


def code_digits(lot: str, rule: str) -> int | None:
    """Digits of the code that encode the year under ``rule`` (None if the code has none)."""
    m = _DIGITS.findall(str(lot or ""))
    if not m:
        return None
    digits = "".join(m)
    if rule == "digits_first1":
        return int(digits[0])
    if rule == "digits_first2":
        return int(digits[:2]) if len(digits) >= 2 else None
    if rule == "digits_last1":
        return int(digits[-1])
    if rule == "digits_last2":
        return int(digits[-2:]) if len(digits) >= 2 else None
    msg = f"unknown lot code rule {rule!r}"
    raise ValueError(msg)


CODE_RULES = ("digits_first1", "digits_first2", "digits_last1", "digits_last2")


def _modulus(rule: str) -> int:
    return 10 if rule.endswith("1") else 100


def release_year_from_code(lot: str, reference_year: int, rule: str = "digits_first1") -> int | None:
    """Latest year not after ``reference_year`` whose last digit(s) match the code."""
    d = code_digits(lot, rule)
    if d is None:
        return None
    mod = _modulus(rule)
    return reference_year - ((reference_year - d) % mod)


def lot_status(release_year: float | None, vaccination_year: float | None, shelf_life_years: int) -> str:
    """``valid`` / ``expired`` / ``before_release`` / ``not_assessable``."""
    if release_year is None or vaccination_year is None or pd.isna(release_year) or pd.isna(vaccination_year):
        return "not_assessable"
    if vaccination_year < release_year:
        return "before_release"
    if vaccination_year > release_year + shelf_life_years:
        return "expired"
    return "valid"


@dataclass(frozen=True)
class CodeRuleCheck:
    rule: str
    n_lots: int
    agreement_exact: float  # code digits == production year (mod 10 or 100)
    agreement_within1: float  # release in the production year or the next one
    accepted: bool


def check_code_rules(lots: pd.DataFrame, rules: list[str], min_agreement: float) -> list[CodeRuleCheck]:
    """Agreement of each rule with the production year recorded in the lots workbook.

    The workbook records the production year; the code carries the release year, which is the
    production year or the following one. A rule is accepted when it reproduces one of the two
    for at least ``min_agreement`` of the lots.
    """
    d = lots.dropna(subset=["production_year"])
    out = []
    for rule in rules:
        mod = _modulus(rule)
        vals = [(code_digits(str(k), rule), int(y)) for k, y in zip(d["lot_exact"], d["production_year"], strict=True)]
        vals = [(c, y) for c, y in vals if c is not None]
        n = len(vals)
        exact = sum(c == y % mod for c, y in vals) / n if n else 0.0
        within = sum(c in (y % mod, (y + 1) % mod) for c, y in vals) / n if n else 0.0
        out.append(CodeRuleCheck(rule, n, exact, within, n > 0 and within >= min_agreement))
    return out


def rule_table(checks: list[CodeRuleCheck]) -> list[dict[str, Any]]:
    return [
        {
            "rule": c.rule,
            "n_lots": c.n_lots,
            "agreement_exact": c.agreement_exact,
            "agreement_within1": c.agreement_within1,
            "accepted": c.accepted,
        }
        for c in checks
    ]
