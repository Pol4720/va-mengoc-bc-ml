"""Exact PELT change-point detection for shifts in mean (Killick, Fearnhead &
Eckley, JASA 2012), with an O(1) segment cost from cumulative sums.

For a segment x[s:t] the cost is the within-segment sum of squares
``Σ x² − (Σ x)² / (t − s)``; the penalised objective is minimised exactly,
and candidate change points are pruned when they can no longer be optimal.
Results coincide with ``ruptures.Pelt(model="l2", jump=1)`` (checked in the
test suite) at a fraction of the cost.
"""

from __future__ import annotations

import numpy as np

__all__ = ["pelt_l2"]


def pelt_l2(x: np.ndarray, pen: float, min_size: int = 2) -> list[int]:
    """Return segment end indices (exclusive), the last one being ``len(x)``."""
    x = np.asarray(x, dtype=float).ravel()
    n = len(x)
    if n == 0:
        return []
    if n < 2 * min_size:
        return [n]
    cs = np.concatenate([[0.0], np.cumsum(x)])
    cs2 = np.concatenate([[0.0], np.cumsum(x * x)])

    def cost(s: np.ndarray, t: int) -> np.ndarray:
        m = t - s
        seg = cs[t] - cs[s]
        return np.asarray((cs2[t] - cs2[s]) - seg * seg / m, dtype=float)

    f = np.full(n + 1, np.inf)
    f[0] = -pen
    last = np.zeros(n + 1, dtype=int)
    candidates = np.array([0], dtype=int)
    for t in range(min_size, n + 1):
        eligible = candidates[t - candidates >= min_size]
        waiting = candidates[t - candidates < min_size]
        vals = f[eligible] + cost(eligible, t) + pen
        i = int(np.argmin(vals))
        f[t] = vals[i]
        last[t] = int(eligible[i])
        kept = eligible[vals - pen <= f[t] + 1e-12]
        candidates = np.concatenate([kept, waiting, [t]]) if t >= min_size else candidates
    bkps = []
    t = n
    while t > 0:
        bkps.append(t)
        t = int(last[t])
    return sorted(bkps)
