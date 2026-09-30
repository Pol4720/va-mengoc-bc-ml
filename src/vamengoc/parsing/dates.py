"""Date parsing for hand-entered spreadsheet cells.

Cells may hold native Excel datetimes, Excel serial numbers (as numbers or
text), day-first strings in several separators, ISO strings, Spanish month
names, or the sentinel ``"N"`` (not applicable). Day-first is the Cuban
convention; a month-first reading is used only when day-first is impossible
and is flagged as a recovery.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

from vamengoc.parsing.text import MISSING_TOKENS, NOT_APPLICABLE_TOKENS, normalize_text
from vamengoc.parsing.values import Parsed, Status

__all__ = ["EXCEL_EPOCH", "excel_serial_to_date", "parse_date"]

EXCEL_EPOCH = dt.date(1899, 12, 30)  # Excel's 1900 system incl. the Lotus leap-year bug
_SERIAL_MIN, _SERIAL_MAX = 10_000, 80_000  # 1927-05-18 .. 2119-01-10

_MONTHS = {
    "ENE": 1,
    "ENERO": 1,
    "JAN": 1,
    "JANUARY": 1,
    "FEB": 2,
    "FEBRERO": 2,
    "FEBRUARY": 2,
    "MAR": 3,
    "MARZO": 3,
    "MARCH": 3,
    "ABR": 4,
    "ABRIL": 4,
    "APR": 4,
    "APRIL": 4,
    "MAY": 5,
    "MAYO": 5,
    "JUN": 6,
    "JUNIO": 6,
    "JUNE": 6,
    "JUL": 7,
    "JULIO": 7,
    "JULY": 7,
    "AGO": 8,
    "AGOSTO": 8,
    "AUG": 8,
    "AUGUST": 8,
    "SEP": 9,
    "SEPT": 9,
    "SET": 9,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTUBRE": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVIEMBRE": 11,
    "NOVEMBER": 11,
    "DIC": 12,
    "DICIEMBRE": 12,
    "DEC": 12,
    "DECEMBER": 12,
}

_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$")
_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$")
_SERIAL = re.compile(r"^\d{5}(?:\.\d+)?$")
_WORDY = re.compile(r"^(\d{1,2})\s*(?:DE\s+)?([A-Z]{3,10})\.?\s*(?:DE\s+|DEL\s+)?(\d{2}|\d{4})$")


def excel_serial_to_date(serial: float) -> dt.date:
    """Convert an Excel 1900-system serial number to a date."""
    return EXCEL_EPOCH + dt.timedelta(days=int(serial))


def _expand_year(y: int, pivot: int) -> int:
    if y >= 100:
        return y
    return 2000 + y if y <= pivot else 1900 + y


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date(value: Any, *, two_digit_pivot: int = 30) -> Parsed[dt.date]:
    """Parse one cell into a :class:`datetime.date`.

    Returns status ``not_applicable`` for the 'N'/'no procede' sentinels,
    ``missing`` for blanks, ``recovered`` for serial numbers stored as text and
    month-first readings, and ``invalid`` for anything uninterpretable.
    """
    if value is None:
        return Parsed(None, Status.MISSING)
    if isinstance(value, dt.datetime):
        return Parsed(value.date(), Status.OK)
    if isinstance(value, dt.date):
        return Parsed(value, Status.OK)
    if isinstance(value, bool):
        return Parsed(None, Status.INVALID)
    if isinstance(value, int | float):
        if math.isnan(float(value)):
            return Parsed(None, Status.MISSING)
        if _SERIAL_MIN <= float(value) <= _SERIAL_MAX:
            return Parsed(excel_serial_to_date(float(value)), Status.RECOVERED)
        return Parsed(None, Status.INVALID)

    raw = str(value).strip()
    token = normalize_text(raw)
    if token in NOT_APPLICABLE_TOKENS:
        return Parsed(None, Status.NOT_APPLICABLE)
    if token in MISSING_TOKENS:
        return Parsed(None, Status.MISSING)

    s = raw.replace(" ", " ").strip()
    if _SERIAL.match(s):
        serial = float(s)
        if _SERIAL_MIN <= serial <= _SERIAL_MAX:
            return Parsed(excel_serial_to_date(serial), Status.RECOVERED)
        return Parsed(None, Status.INVALID)

    m = _ISO.match(s)
    if m:
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return Parsed(d, Status.OK) if d else Parsed(None, Status.INVALID)

    m = _DMY.match(s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        y = _expand_year(int(m.group(3)), two_digit_pivot)
        d = _safe_date(y, b, a)  # day-first (Cuban convention)
        if d is not None:
            return Parsed(d, Status.OK)
        d = _safe_date(y, a, b)  # month-first fallback, flagged
        return Parsed(d, Status.RECOVERED) if d else Parsed(None, Status.INVALID)

    m = _WORDY.match(token)
    if m and m.group(2) in _MONTHS:
        y = _expand_year(int(m.group(3)), two_digit_pivot)
        d = _safe_date(y, _MONTHS[m.group(2)], int(m.group(1)))
        return Parsed(d, Status.RECOVERED) if d else Parsed(None, Status.INVALID)

    return Parsed(None, Status.INVALID)
