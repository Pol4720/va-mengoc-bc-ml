"""Lot identifier normalisation.

Lot numbers are identifiers, never numbers: they are always handled as text.
Cells may hold several lots (co-administration), integers or floats (``575`` /
``575.0``), stray spaces and separators (``"M 575"``, ``"575-M"``) and even a
value Excel converted into a date, which cannot be recovered and is flagged.

Two keys are produced:

* ``exact key`` — upper-case alphanumerics only (``"m-575 "`` → ``"M575"``);
* ``core key`` — the letter prefix/suffix order made irrelevant
  (``"M575"`` and ``"575M"`` → ``"575:M"``), used only when it identifies a
  single lot in the reference table.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from vamengoc.parsing.text import MISSING_TOKENS, cell_to_str, normalize_text, strip_accents
from vamengoc.parsing.values import Parsed, Status

__all__ = ["LotKey", "core_key", "exact_key", "parse_lots"]

_PREFIX = re.compile(r"^(?:LOTE|LOT|NO|N|NRO|NUM|#)\s*[.:#]?\s*(?=\w*\d)", re.IGNORECASE)
_MULTI_SPLIT = re.compile(r"\s*(?:,|;|/|\+|&|\s+Y\s+)\s*")
_ALNUM = re.compile(r"[^0-9A-Z]")
_CORE = re.compile(r"^([A-Z]*)(\d+)([A-Z]*\d?[A-Z]*)$")


def exact_key(lot: str) -> str:
    """Upper-case alphanumeric key: ``"m-575 "`` → ``"M575"``."""
    return _ALNUM.sub("", strip_accents(lot).upper())


def core_key(lot: str) -> str | None:
    """Order-insensitive key separating digits from letters.

    ``"M575"``, ``"575M"``, ``"M 575"`` → ``"575:M"``; suffixes after the letter
    are kept (``"575MX"`` → ``"575:MX"``) so that sub-lots are not merged.
    Returns ``None`` for shapes that do not contain a single digit block.
    """
    k = exact_key(lot)
    m = _CORE.match(k)
    if not m:
        return None
    prefix, digits, suffix = m.groups()
    letters = "".join(sorted(prefix)) + suffix
    return f"{int(digits)}:{letters}"


@dataclass(frozen=True, slots=True)
class LotKey:
    raw: str
    exact: str
    core: str | None


def parse_lots(value: Any) -> Parsed[tuple[LotKey, ...]]:
    """Split a cell into its lot identifiers."""
    if value is None:
        return Parsed(None, Status.MISSING)
    if isinstance(value, dt.datetime | dt.date):
        return Parsed(None, Status.INVALID)  # identifier destroyed by date conversion
    text = cell_to_str(value)
    if text is None or normalize_text(text) in MISSING_TOKENS:
        return Parsed(None, Status.MISSING)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}( .*)?", text):
        return Parsed(None, Status.INVALID)
    parts = [p for p in _MULTI_SPLIT.split(strip_accents(text).upper()) if p.strip()]
    keys: list[LotKey] = []
    for part in parts:
        cleaned = _PREFIX.sub("", part.strip())
        ek = exact_key(cleaned)
        if not ek or not any(ch.isdigit() for ch in ek):
            continue
        keys.append(LotKey(raw=part.strip(), exact=ek, core=core_key(cleaned)))
    if not keys:
        return Parsed(None, Status.INVALID)
    return Parsed(tuple(keys), Status.OK)
