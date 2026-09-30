"""Consistency of lots across destinations (national programme vs export).

Per attribute, equivalence is tested with Schuirmann's two one-sided tests
(TOST, Welch variant) against a margin expressed as a fraction of the
specification window, and the Hodges–Lehmann shift with its distribution-free
confidence interval is reported. The multivariate profiles are compared with
the energy-distance permutation test (Székely & Rizzo 2004).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

__all__ = ["energy_test", "hodges_lehmann", "tost_welch"]


def tost_welch(x: np.ndarray, y: np.ndarray, margin: float, alpha: float = 0.05) -> dict[str, Any]:
    """TOST for |mean(x) − mean(y)| < margin with Welch degrees of freedom."""
    x = np.asarray(x, float)[np.isfinite(x)]
    y = np.asarray(y, float)[np.isfinite(y)]
    nx, ny = len(x), len(y)
    if nx < 3 or ny < 3:
        return {"estimable": False, "n_x": nx, "n_y": ny}
    diff = float(np.mean(x) - np.mean(y))
    vx, vy = np.var(x, ddof=1) / nx, np.var(y, ddof=1) / ny
    se = math.sqrt(vx + vy)
    df = (vx + vy) ** 2 / (vx**2 / (nx - 1) + vy**2 / (ny - 1)) if se > 0 else float(nx + ny - 2)
    if se == 0:
        p_lower = p_upper = 0.0 if abs(diff) < margin else 1.0
    else:
        p_lower = float(stats.t.sf((diff + margin) / se, df))  # H0: diff <= -margin
        p_upper = float(stats.t.cdf((diff - margin) / se, df))  # H0: diff >= +margin
    tcrit = float(stats.t.ppf(1 - alpha, df))
    return {
        "estimable": True,
        "n_x": nx,
        "n_y": ny,
        "diff": diff,
        "se": se,
        "df": df,
        "ci90_lo": diff - tcrit * se,
        "ci90_hi": diff + tcrit * se,
        "margin": margin,
        "p_tost": max(p_lower, p_upper),
        "equivalent": max(p_lower, p_upper) < alpha,
    }


def hodges_lehmann(x: np.ndarray, y: np.ndarray, alpha: float = 0.05) -> dict[str, float]:
    """Hodges–Lehmann location shift (x − y) with the Mann–Whitney-based CI."""
    x = np.asarray(x, float)[np.isfinite(x)]
    y = np.asarray(y, float)[np.isfinite(y)]
    nx, ny = len(x), len(y)
    diffs = np.sort(np.subtract.outer(x, y).ravel())
    est = float(np.median(diffs))
    z = float(stats.norm.ppf(1 - alpha / 2))
    k = math.floor(nx * ny / 2 - z * math.sqrt(nx * ny * (nx + ny + 1) / 12))
    k = max(0, min(k, len(diffs) - 1))
    return {"shift": est, "lo": float(diffs[k]), "hi": float(diffs[len(diffs) - 1 - k])}


def _energy_from_distances(dist: np.ndarray, in_a: np.ndarray) -> float:
    a = in_a
    b = ~in_a
    n, m = int(a.sum()), int(b.sum())
    dab = dist[np.ix_(a, b)].mean()
    daa = dist[np.ix_(a, a)].mean()
    dbb = dist[np.ix_(b, b)].mean()
    return float(n * m / (n + m) * (2 * dab - daa - dbb))


def energy_test(a: np.ndarray, b: np.ndarray, *, n_perm: int = 999, seed: int = 0) -> dict[str, Any]:
    """Two-sample energy-distance test with a permutation p-value (distances computed once)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    pooled = np.vstack([a, b])
    dist = np.sqrt(((pooled[:, None, :] - pooled[None, :, :]) ** 2).sum(-1))
    labels = np.zeros(len(pooled), bool)
    labels[: len(a)] = True
    stat = _energy_from_distances(dist, labels)
    rng = np.random.default_rng(seed)
    count = 0
    for _ in range(n_perm):
        if _energy_from_distances(dist, rng.permutation(labels)) >= stat:
            count += 1
    return {"statistic": stat, "p_value": (count + 1) / (n_perm + 1), "n_perm": n_perm, "n_a": len(a), "n_b": len(b)}
