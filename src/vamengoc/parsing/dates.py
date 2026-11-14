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

__all__ = ["EXCEL_EPOCH", "excel_serial_to_date", "parse_date", "repair_report_dates"]

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


def _with_year(d: dt.date, year: int) -> dt.date | None:
    return _safe_date(year, d.month, d.day)


def repair_report_dates(
    vaccination: dt.date | None,
    notification: dt.date | None,
    file_year: int,
    *,
    max_delay_days: int = 365,
) -> tuple[dt.date | None, dt.date | None, str, str]:
    """Correct mistyped years of the vaccination and notification dates of one report.

    Each annual workbook holds the notifications of its year, which may concern vaccinations
    of the previous year. A vaccination year outside ``[file_year - 1, file_year]`` or a
    notification year outside ``[file_year - 1, file_year + 1]`` is a typing error (2029 or
    2002 in the 2019 workbook). The year is replaced only when exactly the day and month are
    kept and the corrected pair is coherent (0 <= notification - vaccination <= max delay);
    among coherent corrections the shortest delay wins. Otherwise the impossible date is
    dropped (set to None) and the analysis falls back to the other date or the file year.

    Two dates that are both outside the workbook year but consistent with each other are kept
    (an old vaccination reported late is not a typing error).

    Returns ``(vaccination, notification, vaccination_rule, notification_rule)`` where a rule
    is ``kept``, ``kept_consistent``, ``imputed_year`` or ``dropped_impossible``.
    """
    v_ok = vaccination is not None and file_year - 1 <= vaccination.year <= file_year
    n_ok = notification is not None and file_year - 1 <= notification.year <= file_year + 1
    v_rule = n_rule = "kept"

    def coherent(v: dt.date | None, n: dt.date | None) -> bool:
        if v is None or n is None:
            return True
        return 0 <= (n - v).days <= max_delay_days

    if (
        vaccination is not None
        and notification is not None
        and not v_ok
        and not n_ok
        and coherent(vaccination, notification)
    ):
        # Both dates outside the workbook year but consistent with each other: an old vaccination
        # reported late (or a report filed in another year's workbook), not a typing error.
        return vaccination, notification, "kept_consistent", "kept_consistent"
    if vaccination is not None and not v_ok and n_ok and coherent(vaccination, notification):
        # A vaccination just outside the window (e.g. early January of the next year) that agrees
        # with a valid notification date is a real date, not a typing error.
        v_ok, v_rule = True, "kept_consistent"
    if vaccination is not None and not v_ok:
        ref = notification if n_ok else None
        cands = [c for y in (file_year, file_year - 1) if (c := _with_year(vaccination, y)) is not None]
        cands = [c for c in cands if coherent(c, ref)]
        if ref is not None:
            ref_n = ref
            cands.sort(key=lambda c: (ref_n - c).days)
        elif cands:
            cands = [cands[0]]  # no reference: the file year (the workbook's own year)
        if cands:
            vaccination, v_rule = cands[0], "imputed_year"
        else:
            vaccination, v_rule = None, "dropped_impossible"
    if notification is not None and not n_ok:
        ref = vaccination
        cands = [c for y in (file_year, file_year + 1, file_year - 1) if (c := _with_year(notification, y)) is not None]
        cands = [c for c in cands if coherent(ref, c)]
        if ref is not None:
            ref_v = ref
            cands.sort(key=lambda c: (c - ref_v).days)
        elif cands:
            cands = [cands[0]]
        if cands:
            notification, n_rule = cands[0], "imputed_year"
        else:
            notification, n_rule = None, "dropped_impossible"
    return vaccination, notification, v_rule, n_rule
