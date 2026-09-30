"""Small statistical helpers shared by the analysis modules."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy import stats

__all__ = [
    "benjamini_hochberg",
    "expit",
    "logit",
    "poisson_exact_ci",
    "wilson_ci",
]


def poisson_exact_ci(k: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact (Garwood) confidence interval for a Poisson count."""
    if k < 0:
        msg = "count must be non-negative"
        raise ValueError(msg)
    lo = 0.0 if k == 0 else float(stats.chi2.ppf(alpha / 2, 2 * k) / 2)
    hi = float(stats.chi2.ppf(1 - alpha / 2, 2 * k + 2) / 2)
    return lo, hi


def wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (math.nan, math.nan)
    z = float(stats.norm.ppf(1 - alpha / 2))
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def benjamini_hochberg(pvalues: Sequence[float]) -> np.ndarray:
    """Benjamini–Hochberg adjusted p-values (NaNs are kept as NaN)."""
    p = np.asarray(pvalues, dtype=float)
    out = np.full_like(p, np.nan)
    mask = ~np.isnan(p)
    m = int(mask.sum())
    if m == 0:
        return out
    pv = p[mask]
    order = np.argsort(pv)
    ranked = pv[order] * m / (np.arange(m) + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    res = np.empty(m)
    res[order] = np.minimum(adj, 1.0)
    out[mask] = res
    return out


def logit(p: float | np.ndarray) -> float | np.ndarray:
    return np.log(p) - np.log1p(-np.asarray(p))  # type: ignore[no-any-return]


def expit(x: float | np.ndarray) -> float | np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x)))  # type: ignore[no-any-return]
