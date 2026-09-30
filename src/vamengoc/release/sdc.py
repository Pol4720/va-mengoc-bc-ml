"""Statistical disclosure control (SDC) for released tables.

Rules (Hundepool et al., *Statistical Disclosure Control*, Wiley 2012; the
data description's requirement of small-cell suppression):

1. **Primary suppression.** Any count between 1 and ``min_cell − 1`` is replaced
   by the suppression token (default ``"<5"``). Zeros are kept.
2. **Derived-value suppression.** Percentages, rates, ratios and model outputs
   computed from a suppressed count are suppressed too, because they allow the
   count to be recovered.
3. **Secondary (complementary) suppression.** In a table with published
   margins, a row or column with exactly one suppressed cell gets its smallest
   remaining non-zero cell suppressed as well, so the suppressed value cannot
   be obtained by subtraction.

Every suppression is logged (counts of cells only) in the release manifest.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["SDCLog", "suppress_counts", "suppress_linked", "suppress_wide_secondary"]


@dataclass
class SDCLog:
    tables: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, table: str, kind: str, n: int) -> None:
        self.tables.setdefault(table, {"primary": 0, "derived": 0, "secondary": 0})
        self.tables[table][kind] += int(n)

    def total(self) -> dict[str, int]:
        out = {"primary": 0, "derived": 0, "secondary": 0}
        for v in self.tables.values():
            for k in out:
                out[k] += v.get(k, 0)
        return out


def _is_small(v: Any, min_cell: int) -> bool:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return (not np.isnan(x)) and 0 < x < min_cell


def suppress_counts(
    df: pd.DataFrame,
    count_cols: Iterable[str],
    *,
    min_cell: int,
    token: str,
    derived: dict[str, list[str]] | None = None,
    table: str = "",
    log: SDCLog | None = None,
) -> pd.DataFrame:
    """Apply primary suppression to ``count_cols`` and derived-value suppression.

    ``derived`` maps a count column to the columns computed from it (in the same
    row) that must be blanked when the count is suppressed.
    """
    out = df.copy()
    derived = derived or {}
    for col in count_cols:
        if col not in out:
            continue
        mask = out[col].map(lambda v: _is_small(v, min_cell))
        n = int(mask.sum())
        if n:
            out[col] = out[col].astype(object)
            out.loc[mask, col] = token
            if log is not None:
                log.add(table, "primary", n)
            for dcol in derived.get(col, []):
                if dcol in out:
                    out[dcol] = out[dcol].astype(object)
                    k = int((mask & out[dcol].notna()).sum())
                    out.loc[mask, dcol] = None
                    if log is not None:
                        log.add(table, "derived", k)
    return out


def suppress_linked(
    df: pd.DataFrame, trigger_col: str, cols: list[str], *, min_cell: int, table: str = "", log: SDCLog | None = None
) -> pd.DataFrame:
    """Blank ``cols`` in rows where ``trigger_col`` (a count) is small (1..min_cell-1)."""
    out = df.copy()
    mask = out[trigger_col].map(lambda v: _is_small(v, min_cell))
    for c in cols:
        if c in out:
            out[c] = out[c].astype(object)
            k = int((mask & out[c].notna()).sum())
            out.loc[mask, c] = None
            if log is not None:
                log.add(table, "derived", k)
    return out


def suppress_wide_secondary(
    wide: pd.DataFrame, value_cols: list[str], *, min_cell: int, token: str, table: str = "", log: SDCLog | None = None
) -> pd.DataFrame:
    """Primary + secondary suppression on a wide contingency table (rows × value_cols).

    Iterates until every row and every column has either zero or at least two
    suppressed cells.
    """
    vals = wide[value_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    supp = (vals > 0) & (vals < min_cell)
    n_primary = int(supp.sum())
    changed = True
    n_secondary = 0
    while changed:
        changed = False
        for axis in (0, 1):
            lines = supp if axis == 1 else supp.T
            v = vals if axis == 1 else vals.T
            for i in range(lines.shape[0]):
                if lines[i].sum() == 1:
                    cand = np.where(~lines[i] & (v[i] > 0))[0]
                    if len(cand):
                        j = cand[np.argmin(v[i][cand])]
                        if axis == 1:
                            supp[i, j] = True
                        else:
                            supp[j, i] = True
                        n_secondary += 1
                        changed = True
    out = wide.copy()
    for j, c in enumerate(value_cols):
        out[c] = out[c].astype(object)
        out.loc[supp[:, j], c] = token
    if log is not None:
        log.add(table, "primary", n_primary)
        log.add(table, "secondary", n_secondary)
    return out
