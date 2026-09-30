"""Multivariate statistical process control of lot-release profiles.

Lots are points in the space of their quantitative attributes (on analysis
scales). A robust centre and scale (minimum covariance determinant, Rousseeuw
1984) standardise the data, PCA summarises correlated variation, and two
statistics monitor each lot (MacGregor & Kourti 1995):

* Hotelling's T² in the retained principal subspace (unusual *combination*
  of attribute levels within the usual correlation structure) with the
  Phase I Beta-distribution limit (Tracy, Young & Mason 1992);
* the squared prediction error SPE/Q (break of the correlation structure),
  with the Jackson–Mudholkar limit.

Per-lot contributions identify which attributes drive a flagged profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.covariance import MinCovDet

__all__ = ["MSPCResult", "fit_mspc"]


@dataclass
class MSPCResult:
    attributes: list[str]
    n_components: int
    explained_variance: np.ndarray
    loadings: pd.DataFrame
    scores: pd.DataFrame  # per lot: T2, SPE, flags, atypicality percentile
    t2_limit: float
    spe_limit: float
    contributions: pd.DataFrame  # per lot x attribute contribution to T2
    notes: list[str] = field(default_factory=list)


def _jackson_mudholkar(eigs_residual: np.ndarray, alpha: float) -> float:
    t1 = float(np.sum(eigs_residual))
    t2 = float(np.sum(eigs_residual**2))
    t3 = float(np.sum(eigs_residual**3))
    if t1 <= 0 or t2 <= 0:
        return 0.0
    h0 = 1 - 2 * t1 * t3 / (3 * t2**2)
    if h0 <= 0:  # fall back to Box's approximation
        g = t2 / t1
        h = t1**2 / t2
        return float(g * stats.chi2.ppf(1 - alpha, h))
    ca = float(stats.norm.ppf(1 - alpha))
    val = t1 * (ca * np.sqrt(2 * t2 * h0**2) / t1 + 1 + t2 * h0 * (h0 - 1) / t1**2) ** (1 / h0)
    return float(val)


def fit_mspc(data: pd.DataFrame, *, alpha: float = 0.01, variance_target: float = 0.85, seed: int = 0) -> MSPCResult:
    """Fit a robust PCA model on complete rows of ``data`` (index = lot key)."""
    notes: list[str] = []
    complete = data.dropna()
    if len(complete) < len(data):
        notes.append(f"{len(data) - len(complete)} lots with missing attributes excluded")
    x = complete.to_numpy(dtype=float)
    n, p = x.shape
    mcd = MinCovDet(random_state=seed, support_fraction=None).fit(x)
    centre = mcd.location_
    scale = np.sqrt(np.diag(mcd.covariance_))
    scale[scale <= 0] = 1.0
    z = (x - centre) / scale
    corr = mcd.covariance_ / np.outer(scale, scale)
    eigval, eigvec = np.linalg.eigh(corr)
    order = np.argsort(eigval)[::-1]
    eigval, eigvec = eigval[order], eigvec[:, order]
    eigval = np.clip(eigval, 1e-12, None)
    explained = eigval / eigval.sum()
    a = int(np.searchsorted(np.cumsum(explained), variance_target) + 1)
    a = max(1, min(a, p - 1)) if p > 1 else 1
    p_a = eigvec[:, :a]
    t = z @ p_a
    t2 = np.sum(t**2 / eigval[:a], axis=1)
    resid = z - t @ p_a.T
    spe = np.sum(resid**2, axis=1)
    t2_limit = float((n - 1) ** 2 / n * stats.beta.ppf(1 - alpha, a / 2, (n - a - 1) / 2))
    spe_limit = _jackson_mudholkar(eigval[a:], alpha)
    # contributions to T2: sum over components of (t_i,k / λ_k) p_jk z_ij
    contrib = np.zeros_like(z)
    for k in range(a):
        contrib += (t[:, [k]] / eigval[k]) * (p_a[:, k][None, :] * z)
    scores = pd.DataFrame(
        {"t2": t2, "spe": spe, "t2_flag": t2 > t2_limit, "spe_flag": spe > spe_limit}, index=complete.index
    )
    scores["atypicality_pct"] = scores["t2"].rank(pct=True) * 100
    scores["robust_distance"] = np.sqrt(mcd.mahalanobis(x))
    loadings = pd.DataFrame(p_a, index=complete.columns, columns=[f"PC{i + 1}" for i in range(a)])
    contributions = pd.DataFrame(contrib, index=complete.index, columns=complete.columns)
    return MSPCResult(
        attributes=list(complete.columns),
        n_components=a,
        explained_variance=explained,
        loadings=loadings,
        scores=scores,
        t2_limit=t2_limit,
        spe_limit=spe_limit,
        contributions=contributions,
        notes=notes,
    )


def flagged_summary(result: MSPCResult, years: pd.Series) -> pd.DataFrame:
    """Share of lots beyond the T² and SPE limits by production year."""
    s = result.scores.join(years.rename("production_year"), how="left")
    g = s.groupby("production_year")
    return pd.DataFrame(
        {"n_lots": g.size(), "t2_flagged": g["t2_flag"].sum(), "spe_flagged": g["spe_flag"].sum()}
    ).reset_index()


def top_contributors(result: MSPCResult, k: int = 3) -> dict[str, Any]:
    """How often each attribute is among the k largest contributors in flagged lots."""
    flagged = result.scores.index[result.scores["t2_flag"] | result.scores["spe_flag"]]
    counts: dict[str, int] = dict.fromkeys(result.attributes, 0)
    for lot in flagged:
        top = result.contributions.loc[lot].abs().sort_values(ascending=False).head(k).index
        for a in top:
            counts[a] += 1
    return {"n_flagged": len(flagged), "top_contributor_counts": counts}
