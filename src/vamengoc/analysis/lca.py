"""Latent class analysis (Bernoulli mixture) of co-reported AEFI indicators.

The model assumes K latent reactogenicity phenotypes; within a class the J
event indicators are independent Bernoulli variables (local independence):

    P(x) = Σ_k π_k Π_j θ_kj^{x_j} (1 − θ_kj)^{1 − x_j}

Parameters are estimated by EM with many random starts. Missing indicators are
integrated out (missing at random). Item probabilities receive a weak
Beta(1.5, 1.5) prior (MAP) to keep estimates off the 0/1 boundary. The number
of classes is chosen by BIC; ICL-BIC, entropy and bootstrap stability
(adjusted Rand index against refits on resampled data) are reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score

__all__ = ["LCAFit", "fit_lca", "select_lca"]

_PRIOR_A = 1.5  # Beta(a, a) prior on item probabilities


@dataclass
class LCAFit:
    k: int
    weights: np.ndarray  # (K,)
    theta: np.ndarray  # (K, J)
    loglik: float
    n_obs: int
    n_items: int
    n_iter: int
    converged: bool
    posterior: np.ndarray = field(repr=False)  # (n, K)

    @property
    def n_params(self) -> int:
        return (self.k - 1) + self.k * self.n_items

    @property
    def bic(self) -> float:
        return float(-2 * self.loglik + self.n_params * np.log(self.n_obs))

    @property
    def aic(self) -> float:
        return -2 * self.loglik + 2 * self.n_params

    @property
    def entropy_r2(self) -> float:
        """Relative entropy (1 = perfectly separated classes)."""
        if self.k == 1:
            return 1.0
        p = np.clip(self.posterior, 1e-300, 1)
        ent = -np.sum(p * np.log(p))
        return float(1 - ent / (self.n_obs * np.log(self.k)))

    @property
    def icl_bic(self) -> float:
        p = np.clip(self.posterior, 1e-300, 1)
        return self.bic + 2 * float(-np.sum(p * np.log(p)))

    def assign(self) -> np.ndarray:
        return np.asarray(np.argmax(self.posterior, axis=1))


def _loglik_matrix(x: np.ndarray, obs: np.ndarray, theta: np.ndarray, weights: np.ndarray) -> np.ndarray:
    lt = np.log(np.clip(theta, 1e-12, 1 - 1e-12))
    l1t = np.log(np.clip(1 - theta, 1e-12, 1))
    # (n, K): Σ_j obs_ij [x_ij log θ_kj + (1 − x_ij) log(1 − θ_kj)]
    return np.asarray((x * obs) @ lt.T + ((1 - x) * obs) @ l1t.T + np.log(weights)[None, :])


def _em(x: np.ndarray, obs: np.ndarray, k: int, rng: np.random.Generator, max_iter: int, tol: float) -> LCAFit:
    n, j = x.shape
    weights = rng.dirichlet(np.full(k, 5.0))
    theta = np.clip(rng.beta(1.0, 3.0, size=(k, j)) * 0.9 + 0.02, 0.01, 0.99)
    prev = -np.inf
    converged = False
    it = 0
    for it in range(1, max_iter + 1):  # noqa: B007 - iteration count is reported
        lm = _loglik_matrix(x, obs, theta, weights)
        mx = lm.max(axis=1, keepdims=True)
        ll_rows = mx[:, 0] + np.log(np.exp(lm - mx).sum(axis=1))
        ll = float(ll_rows.sum())
        post = np.exp(lm - ll_rows[:, None])
        nk = post.sum(axis=0)
        weights = np.clip(nk / n, 1e-10, None)
        weights /= weights.sum()
        num = post.T @ (x * obs) + (_PRIOR_A - 1)
        den = post.T @ obs + 2 * (_PRIOR_A - 1)
        theta = num / den
        if abs(ll - prev) < tol * max(1.0, abs(ll)):
            converged = True
            break
        prev = ll
    lm = _loglik_matrix(x, obs, theta, weights)
    mx = lm.max(axis=1, keepdims=True)
    ll_rows = mx[:, 0] + np.log(np.exp(lm - mx).sum(axis=1))
    post = np.exp(lm - ll_rows[:, None])
    return LCAFit(
        k=k,
        weights=weights,
        theta=theta,
        loglik=float(ll_rows.sum()),
        n_obs=n,
        n_items=j,
        n_iter=it,
        converged=converged,
        posterior=post,
    )


def fit_lca(
    data: pd.DataFrame, k: int, *, n_starts: int = 20, max_iter: int = 500, tol: float = 1e-7, seed: int = 0
) -> LCAFit:
    """Best of ``n_starts`` EM runs for K classes; classes ordered by size (descending)."""
    arr = data.astype("Float64").to_numpy(dtype=float, na_value=np.nan)
    obs = (~np.isnan(arr)).astype(float)
    x = np.nan_to_num(arr, nan=0.0)
    rng = np.random.default_rng(seed)
    best: LCAFit | None = None
    for _ in range(n_starts):
        fit = _em(x, obs, k, rng, max_iter, tol)
        if best is None or fit.loglik > best.loglik:
            best = fit
    assert best is not None
    order = np.argsort(-best.weights)
    best.weights = best.weights[order]
    best.theta = best.theta[order]
    best.posterior = best.posterior[:, order]
    return best


def _match_labels(ref: np.ndarray, other: np.ndarray, k: int) -> np.ndarray:
    """Relabel ``other`` to maximise agreement with ``ref`` (Hungarian algorithm)."""
    cost = np.zeros((k, k))
    for a in range(k):
        for b in range(k):
            cost[a, b] = -np.sum((ref == a) & (other == b))
    _, cols = linear_sum_assignment(cost)
    mapping = {int(c): int(r) for r, c in enumerate(cols)}
    return np.array([mapping.get(int(v), int(v)) for v in other])


def select_lca(
    data: pd.DataFrame,
    k_range: tuple[int, int],
    *,
    n_starts: int = 20,
    max_iter: int = 500,
    tol: float = 1e-7,
    seed: int = 0,
    bootstrap: int = 0,
) -> dict[str, Any]:
    """Fit K = k_min..k_max and pick the BIC-optimal model; optional bootstrap stability."""
    fits = {
        k: fit_lca(data, k, n_starts=n_starts, max_iter=max_iter, tol=tol, seed=seed + k)
        for k in range(k_range[0], k_range[1] + 1)
    }
    table = pd.DataFrame(
        [
            {
                "k": k,
                "loglik": f.loglik,
                "n_params": f.n_params,
                "bic": f.bic,
                "aic": f.aic,
                "icl_bic": f.icl_bic,
                "entropy_r2": f.entropy_r2,
                "converged": f.converged,
                "smallest_class_pct": 100 * float(f.weights.min()),
            }
            for k, f in fits.items()
        ]
    )
    best_k = int(table.loc[table["bic"].idxmin(), "k"])
    best = fits[best_k]
    stability: list[float] = []
    if bootstrap and best_k > 1:
        rng = np.random.default_rng(seed + 991)
        ref = best.assign()
        n = len(data)
        for b in range(bootstrap):
            idx = rng.integers(0, n, n)
            refit = fit_lca(
                data.iloc[idx],
                best_k,
                n_starts=max(3, n_starts // 4),
                max_iter=max_iter,
                tol=tol,
                seed=seed + 10_000 + b,
            )
            # predict on the full data with the refitted parameters
            arr = data.astype("Float64").to_numpy(dtype=float, na_value=np.nan)
            obs = (~np.isnan(arr)).astype(float)
            x = np.nan_to_num(arr, nan=0.0)
            pred = np.argmax(_loglik_matrix(x, obs, refit.theta, refit.weights), axis=1)
            stability.append(float(adjusted_rand_score(ref, _match_labels(ref, pred, best_k))))
    return {
        "table": table,
        "best_k": best_k,
        "fit": best,
        "fits": fits,
        "bootstrap_ari": stability,
        "bootstrap_ari_median": float(np.median(stability)) if stability else None,
    }


def class_profiles(fit: LCAFit, items: list[str]) -> pd.DataFrame:
    """Item-response probabilities in long format (class, item, probability)."""
    rows = [
        {"class": k + 1, "class_weight": float(fit.weights[k]), "item": it, "probability": float(fit.theta[k, j])}
        for k in range(fit.k)
        for j, it in enumerate(items)
    ]
    return pd.DataFrame.from_records(rows)
