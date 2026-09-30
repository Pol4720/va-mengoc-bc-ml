"""Small statistical helpers shared by the analysis modules."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

__all__ = [
    "FirthResult",
    "benjamini_hochberg",
    "drop_collinear_columns",
    "expit",
    "firth_logit",
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


def drop_collinear_columns(x: np.ndarray, names: Sequence[str]) -> tuple[list[int], list[str]]:
    """Indices of columns to keep so that ``x`` has full column rank (pivoted QR), and the dropped names.

    Columns are examined in order; a column is dropped when it is (numerically) a linear combination
    of the columns kept before it, so put the columns you care most about first.
    """
    keep: list[int] = []
    dropped: list[str] = []
    for j in range(x.shape[1]):
        trial = x[:, [*keep, j]]
        if np.linalg.matrix_rank(trial) == len(keep) + 1:
            keep.append(j)
        else:
            dropped.append(str(names[j]))
    return keep, dropped


@dataclass(frozen=True)
class FirthResult:
    """Firth-penalised logistic regression fit (Firth 1993; Heinze & Schemper 2002)."""

    params: np.ndarray
    se: np.ndarray
    converged: bool
    n_iter: int
    penalized_loglik: float

    def conf_int(self, alpha: float = 0.05) -> np.ndarray:
        """Wald intervals from the inverse penalised information matrix."""
        z = float(stats.norm.ppf(1 - alpha / 2))
        return np.column_stack([self.params - z * self.se, self.params + z * self.se])

    def pvalues(self) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.asarray(2 * stats.norm.sf(np.abs(self.params / self.se)))


def _firth_pll(x: np.ndarray, y: np.ndarray, beta: np.ndarray, offset: np.ndarray) -> tuple[float, np.ndarray]:
    eta = x @ beta + offset
    p = 1.0 / (1.0 + np.exp(-eta))
    w = np.clip(p * (1 - p), 1e-12, None)
    info = x.T @ (x * w[:, None])
    sign, logdet = np.linalg.slogdet(info)
    ll = float(np.sum(y * eta - np.logaddexp(0.0, eta)))
    return (ll + 0.5 * logdet if sign > 0 else -math.inf), info


def firth_logit(
    x: np.ndarray,
    y: np.ndarray,
    *,
    offset: np.ndarray | None = None,
    max_iter: int = 100,
    tol: float = 1e-8,
    max_step: float = 5.0,
) -> FirthResult:
    """Firth's bias-reduced logistic regression by modified-score Newton iterations with step halving.

    Finite estimates exist under complete or quasi-complete separation, which makes it the standard
    choice for rare binary outcomes. ``x`` must include the intercept column and have full rank.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    off = np.zeros(len(y)) if offset is None else np.asarray(offset, dtype=float)
    beta = np.zeros(x.shape[1])
    pll, info = _firth_pll(x, y, beta, off)
    converged = False
    it = 0
    for it in range(1, max_iter + 1):  # noqa: B007 - iteration count is reported
        eta = x @ beta + off
        p = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(p * (1 - p), 1e-12, None)
        inv = np.linalg.inv(info)
        h = np.einsum("ij,jk,ik->i", x, inv, x) * w  # diagonal of the weighted hat matrix
        score = x.T @ (y - p + h * (0.5 - p))
        step = inv @ score
        big = float(np.max(np.abs(step)))
        if big > max_step:
            step *= max_step / big
        for _ in range(30):  # step halving until the penalised log-likelihood does not decrease
            new_pll, new_info = _firth_pll(x, y, beta + step, off)
            if new_pll >= pll - 1e-10:
                break
            step /= 2
        beta = beta + step
        pll, info = new_pll, new_info
        if float(np.max(np.abs(step))) < tol:
            converged = True
            break
    cov = np.linalg.inv(info)
    return FirthResult(
        params=beta,
        se=np.sqrt(np.clip(np.diag(cov), 0, None)),
        converged=converged,
        n_iter=it,
        penalized_loglik=pll,
    )
