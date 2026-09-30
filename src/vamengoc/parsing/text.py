"""Text normalisation primitives shared by every parser.

The source workbooks are typed by hand across many health areas, so the same
value arrives with different case, accents, punctuation and spacing. These
helpers produce stable keys without ever guessing a value: they only remove
presentation noise.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from functools import lru_cache
from typing import Any

__all__ = [
    "MISSING_TOKENS",
    "NOT_APPLICABLE_TOKENS",
    "cell_to_str",
    "compact",
    "is_missing",
    "normalize_text",
    "strip_accents",
]

_NON_ALNUM = re.compile(r"[^0-9A-Z]+")
_SPACES = re.compile(r"\s+")

# Tokens meaning "no value recorded".
MISSING_TOKENS = frozenset(
    {
        "",
        "-",
        "--",
        "---",
        "NA",
        "N A",
        "NAN",
        "NONE",
        "NULL",
        "ND",
        "S D",
        "SD",
        "SIN DATOS",
        "SIN DATO",
        "NO CONSTA",
        "DESCONOCIDO",
        "DESC",
        "?",
        "NR",
        "NO REFIERE",
    }
)
# Tokens meaning "not applicable" (used, e.g., in date columns for non-hospitalised cases).
NOT_APPLICABLE_TOKENS = frozenset({"N", "NO", "N A", "NO PROCEDE", "NP", "NO APLICA"})


def strip_accents(s: str) -> str:
    """Remove diacritics (á→a, ñ→n, ü→u) using Unicode decomposition."""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(value: Any) -> str:
    """Upper-case, accent-free, punctuation-free, single-spaced representation.

    ``None`` and float NaN map to the empty string. Numbers are rendered without
    a spurious ``.0`` so that ``575`` and ``575.0`` normalise identically.
    Results are memoised per (type, value) — cells repeat heavily in the source.
    """
    try:
        return _normalize_cached(type(value).__name__, value)
    except TypeError:  # unhashable input
        return _normalize_uncached(value)


@lru_cache(maxsize=262_144)
def _normalize_cached(_type: str, value: Any) -> str:
    return _normalize_uncached(value)


def _normalize_uncached(value: Any) -> str:
    s = cell_to_str(value)
    if s is None:
        return ""
    s = strip_accents(s).upper()
    s = _NON_ALNUM.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def compact(value: Any) -> str:
    """:func:`normalize_text` without any spaces — the key used for header matching."""
    return normalize_text(value).replace(" ", "")


def cell_to_str(value: Any) -> str | None:
    """Render a raw spreadsheet cell as text without type inference.

    * ``None``/NaN/NaT → ``None``
    * integers and integer-valued floats → ``"575"``
    * other floats → shortest round-trip representation (``"0.5"``)
    * dates/datetimes → ISO format
    * strings → whitespace-trimmed (non-breaking and thin spaces included)
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "S" if value else "N"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    s = str(value)
    if s in {"nan", "NaN", "NaT", "None"}:
        return None
    s = s.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return s.strip()


def is_missing(value: Any) -> bool:
    """True when a cell carries no information (empty, dash, 'sin datos', …)."""
    return normalize_text(value) in MISSING_TOKENS
