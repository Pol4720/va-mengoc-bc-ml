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
   be obtained by subtraction. Secondary cells are marked ``[c]`` (they are not
   small counts, so they must not carry the ``<5`` token).
4. **Implied counts.** A percentage released next to its denominator implies a
   count (``n × pct / 100``); when that count or its complement is between 1 and
   ``min_cell − 1``, the percentage is blanked.

Every suppression is logged (counts of cells only) in the release manifest.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "SECONDARY_TOKEN",
    "SDCLog",
    "suppress_column_secondary",
    "suppress_counts",
    "suppress_implied_pct",
    "suppress_linked",
    "suppress_long_secondary",
    "suppress_wide_secondary",
]

SECONDARY_TOKEN = "[c]"  # noqa: S105 - disclosure-control marker, not a secret


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
    wide: pd.DataFrame,
    value_cols: list[str],
    *,
    min_cell: int,
    token: str,
    table: str = "",
    log: SDCLog | None = None,
    primary_mask: np.ndarray | None = None,
) -> pd.DataFrame:
    """Primary + secondary suppression on a wide contingency table (rows × value_cols).

    Iterates until every row and every column has either zero or at least two
    suppressed cells. Primary cells get ``token``; complementary cells get
    :data:`SECONDARY_TOKEN`. ``primary_mask`` overrides the small-count rule (cells
    already suppressed upstream).
    """
    vals = wide[value_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    primary = (vals > 0) & (vals < min_cell) if primary_mask is None else primary_mask.astype(bool)
    supp = primary.copy()
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
        out.loc[primary[:, j], c] = token
        out.loc[supp[:, j] & ~primary[:, j], c] = SECONDARY_TOKEN
    if log is not None:
        log.add(table, "primary", n_primary)
        log.add(table, "secondary", n_secondary)
    return out


def suppress_long_secondary(
    df: pd.DataFrame,
    *,
    block_cols: list[str],
    row_col: str,
    group_col: str,
    count_col: str,
    derived: list[str],
    min_cell: int,
    token: str,
    table: str = "",
    log: SDCLog | None = None,
) -> pd.DataFrame:
    """Complementary suppression for long tables of counts by level and group.

    Within each block (e.g. one variable), levels × groups form a table whose
    column totals are published (denominators) and whose groups may include a
    total (``All``). Cells already carrying ``token`` are primary; complementary
    cells are added until no suppressed count can be recovered by subtraction
    along a level or a group, and the ``derived`` columns of every suppressed
    cell are blanked.
    """
    out = df.copy()
    out[count_col] = out[count_col].astype(object)
    for c in derived:
        if c in out:
            out[c] = out[c].astype(object)
    n_secondary = 0
    for _, idx in out.groupby(block_cols, sort=False).groups.items():
        blk = out.loc[idx]
        wide = blk.pivot(index=row_col, columns=group_col, values=count_col)
        groups = list(wide.columns)
        primary = wide.apply(lambda col: col.map(lambda v: isinstance(v, str) and v == token)).to_numpy()
        if not primary.any():
            continue
        numeric = wide.apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy(dtype=float)
        numeric[primary] = 1.0  # any positive placeholder: only the pattern matters
        res = suppress_wide_secondary(
            pd.DataFrame(numeric, index=wide.index, columns=groups).reset_index(),
            groups,
            min_cell=min_cell,
            token=token,
            primary_mask=primary,
        )
        res = res.set_index(row_col)
        for i in idx:
            r, g = out.loc[i, row_col], out.loc[i, group_col]
            if res.loc[r, g] == SECONDARY_TOKEN:
                out.loc[i, count_col] = SECONDARY_TOKEN
                for c in derived:
                    if c in out:
                        out.loc[i, c] = None
                n_secondary += 1
    if log is not None and n_secondary:
        log.add(table, "secondary", n_secondary)
    return out


def suppress_implied_pct(
    df: pd.DataFrame,
    n_col: str,
    pct_cols: list[str],
    *,
    min_cell: int,
    table: str = "",
    log: SDCLog | None = None,
    scale: float = 100.0,
) -> pd.DataFrame:
    """Blank percentages (``scale=100``) or proportions (``scale=1``) whose implied count, or its
    complement, is a small count."""
    out = df.copy()
    n = pd.to_numeric(out[n_col], errors="coerce")
    k_total = 0
    for c in pct_cols:
        if c not in out:
            continue
        pct = pd.to_numeric(out[c], errors="coerce")
        implied = (n * pct / scale).round()
        complement = n - implied
        risky = ((implied > 0) & (implied < min_cell)) | ((complement > 0) & (complement < min_cell))
        risky &= pct.notna()
        if risky.any():
            out[c] = out[c].astype(object)
            out.loc[risky, c] = None
            k_total += int(risky.sum())
    if log is not None and k_total:
        log.add(table, "derived", k_total)
    return out


def suppress_column_secondary(
    df: pd.DataFrame,
    cols: list[str],
    *,
    token: str,
    block_col: str | None = None,
    derived: dict[str, list[str]] | None = None,
    table: str = "",
    log: SDCLog | None = None,
) -> pd.DataFrame:
    """Complementary suppression for columns whose totals are published elsewhere.

    Within each block (or the whole table), a column with exactly one suppressed cell gets its
    smallest remaining positive cell marked :data:`SECONDARY_TOKEN`, so that the suppressed count
    cannot be obtained as the published total minus the visible cells.
    """
    out = df.copy()
    derived = derived or {}
    n_secondary = 0
    blocks = [out.index] if block_col is None else list(out.groupby(block_col, sort=False).groups.values())
    for idx in blocks:
        for c in cols:
            if c not in out:
                continue
            vals = out.loc[idx, c]
            supp = vals.map(lambda v: isinstance(v, str) and v in (token, SECONDARY_TOKEN))
            if int(supp.sum()) != 1:
                continue
            num = pd.to_numeric(vals.where(~supp), errors="coerce")
            cand = num[num > 0]
            if cand.empty:
                continue
            j = cand.idxmin()
            out[c] = out[c].astype(object)
            out.loc[j, c] = SECONDARY_TOKEN
            for d in derived.get(c, []):
                if d in out:
                    out[d] = out[d].astype(object)
                    out.loc[j, d] = None
            n_secondary += 1
    if log is not None and n_secondary:
        log.add(table, "secondary", n_secondary)
    return out
