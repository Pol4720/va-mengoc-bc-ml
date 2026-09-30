"""Univariate statistical process control of lot-release attributes.

* Attributes are analysed on their natural scale or on a variance-stabilising
  transform (log2 titres, log10 IgG, log10(1+x) endotoxin) declared in the schema.
* Every value is also expressed as its position in the specification window
  (0 = lower limit, 1 = upper limit), a scale that allows comparing attributes
  and can be released without disclosing absolute values.
* Capability: Ppk (overall standard deviation) with percentile-bootstrap CI, and
  the percentile-based index of ISO 22514-2 for non-normal data.
* Control charts: individuals chart (moving-range sigma) and EWMA, with the
  Western Electric/Nelson rules most relevant to drift.
* Change points in the lot sequence: exact PELT (Killick et al. 2012) on the
  standardised series with a BIC-type penalty.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from vamengoc.analysis.changepoint import pelt_l2
from vamengoc.parsing.specs import Spec

__all__ = [
    "AttributeScale",
    "attribute_scales",
    "capability",
    "changepoints",
    "control_chart",
    "to_window",
    "transform_values",
]

TRANSFORMS: dict[str | None, Callable[[np.ndarray], np.ndarray]] = {
    "log2": np.log2,
    "log10": np.log10,
    "log10p1": lambda v: np.log10(1 + v),
    None: lambda v: v,
}


@dataclass(frozen=True)
class AttributeScale:
    """Analysis scale of one attribute: transform and (transformed) reference window."""

    name: str
    transform: str | None
    low: float | None  # transformed lower spec limit (None if unbounded)
    high: float | None  # transformed upper spec limit (None if unbounded)
    window_low: float  # finite window used for the 0-1 normalisation
    window_high: float
    spec: Spec
    one_sided: str | None  # "lower", "upper" or None


def transform_values(x: np.ndarray | pd.Series, transform: str | None) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(TRANSFORMS[transform](arr), dtype=float)


def attribute_scales(specs: dict[str, Spec], lots: pd.DataFrame, schema: dict[str, Any]) -> dict[str, AttributeScale]:
    """Build analysis scales from parsed specifications, transforms and natural bounds."""
    transforms: dict[str, str] = schema.get("transforms", {})
    natural: dict[str, dict[str, Any]] = schema.get("natural_bounds", {})
    out: dict[str, AttributeScale] = {}
    for name, spec in specs.items():
        if not spec.is_quantitative or name not in lots:
            continue
        tr = transforms.get(name)
        f = TRANSFORMS[tr]
        lo = None if spec.low is None else float(f(np.array([spec.low]))[0])
        hi = None if spec.high is None else float(f(np.array([spec.high]))[0])
        values = transform_values(lots[name].dropna().to_numpy(dtype=float), tr)
        values = values[np.isfinite(values)]
        nb = natural.get(name, {})
        nat_lo = nb.get("low")
        nat_hi = nb.get("high")
        nat_lo_t = None if nat_lo is None else float(f(np.array([nat_lo]))[0])
        nat_hi_t = None if nat_hi is None else float(f(np.array([nat_hi]))[0])
        one_sided = None
        if lo is not None and hi is not None:
            wl, wh = lo, hi
        elif lo is not None:
            one_sided = "lower"
            wl = lo
            wh = nat_hi_t if nat_hi_t is not None else float(np.nanmax(values)) if len(values) else lo + 1
        elif hi is not None:
            one_sided = "upper"
            wh = hi
            wl = nat_lo_t if nat_lo_t is not None else float(np.nanmin(values)) if len(values) else hi - 1
        else:  # pragma: no cover - quantitative spec always has a bound
            continue
        if wh <= wl:
            wh = wl + 1.0
        out[name] = AttributeScale(name, tr, lo, hi, float(wl), float(wh), spec, one_sided)
    return out


def to_window(values: np.ndarray | pd.Series, scale: AttributeScale) -> np.ndarray:
    """Position within the specification window on the analysis scale (0 → low, 1 → high)."""
    t = transform_values(values, scale.transform)
    return (t - scale.window_low) / (scale.window_high - scale.window_low)


def _ppk(x: np.ndarray, lo: float | None, hi: float | None) -> float:
    mu, sd = float(np.mean(x)), float(np.std(x, ddof=1))
    if sd <= 0:
        return math.inf
    parts = []
    if lo is not None:
        parts.append((mu - lo) / (3 * sd))
    if hi is not None:
        parts.append((hi - mu) / (3 * sd))
    return float(min(parts))


def _ppk_percentile(x: np.ndarray, lo: float | None, hi: float | None) -> float:
    q_lo, med, q_hi = np.quantile(x, [0.00135, 0.5, 0.99865])
    parts = []
    if lo is not None and med > q_lo:
        parts.append((med - lo) / (med - q_lo))
    if hi is not None and q_hi > med:
        parts.append((hi - med) / (q_hi - med))
    return float(min(parts)) if parts else math.inf


def capability(values: np.ndarray, scale: AttributeScale, *, n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Ppk (normal theory) with bootstrap CI and the percentile-based Ppk."""
    x = transform_values(values, scale.transform)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"attribute": scale.name, "n": n, "estimable": False}
    ppk = _ppk(x, scale.low, scale.high)
    rng = np.random.default_rng(seed)
    boots = np.array([_ppk(rng.choice(x, n, replace=True), scale.low, scale.high) for _ in range(n_boot)])
    boots = boots[np.isfinite(boots)]
    conf = [scale.spec.conforms(float(v)) for v in values if np.isfinite(v)]
    return {
        "attribute": scale.name,
        "n": n,
        "estimable": True,
        "transform": scale.transform,
        "mean": float(np.mean(x)),
        "sd": float(np.std(x, ddof=1)),
        "ppk": ppk,
        "ppk_lo": float(np.quantile(boots, 0.025)) if len(boots) else math.nan,
        "ppk_hi": float(np.quantile(boots, 0.975)) if len(boots) else math.nan,
        "ppk_percentile": _ppk_percentile(x, scale.low, scale.high) if n >= 50 else math.nan,
        "pct_conforming": 100.0 * float(np.mean([c for c in conf if c is not None])) if conf else math.nan,
        "one_sided": scale.one_sided,
        "window_position_median": float(np.median((x - scale.window_low) / (scale.window_high - scale.window_low))),
    }


def _nelson(z: np.ndarray) -> dict[str, np.ndarray]:
    """Boolean flags per point for rules 1 (beyond 3σ), 2 (9 same side), 3 (6 trend), 5 (2 of 3 beyond 2σ)."""
    n = len(z)
    r1 = np.abs(z) > 3
    r2 = np.zeros(n, bool)
    r3 = np.zeros(n, bool)
    r5 = np.zeros(n, bool)
    for i in range(n):
        if i >= 8:
            w = z[i - 8 : i + 1]
            r2[i] = bool(np.all(w > 0) or np.all(w < 0))
        if i >= 5:
            d = np.diff(z[i - 5 : i + 1])
            r3[i] = bool(np.all(d > 0) or np.all(d < 0))
        if i >= 2:
            w = z[i - 2 : i + 1]
            r5[i] = bool(np.sum(w > 2) >= 2 or np.sum(w < -2) >= 2)
    return {"rule1": r1, "rule2": r2, "rule3": r3, "rule5": r5}


def control_chart(
    values: np.ndarray, *, baseline: np.ndarray | None = None, ewma_lambda: float = 0.2, ewma_l: float = 3.0
) -> pd.DataFrame:
    """Individuals chart (MR̄/1.128 sigma) and EWMA with exact time-varying limits.

    ``baseline`` (boolean mask) selects the Phase I points used to estimate the
    centre and sigma; by default the whole series (retrospective Phase I).
    """
    x = np.asarray(values, dtype=float)
    base = x if baseline is None else x[np.asarray(baseline, bool)]
    base = base[np.isfinite(base)]
    centre = float(np.mean(base))
    mr = np.abs(np.diff(base))
    sigma = float(np.mean(mr) / 1.128) if len(mr) else float(np.std(base, ddof=1))
    sigma = sigma if sigma > 0 else 1e-12
    z = (x - centre) / sigma
    flags = _nelson(np.nan_to_num(z))
    ew = np.empty_like(x)
    prev = centre
    for i, v in enumerate(x):
        prev = ewma_lambda * (v if np.isfinite(v) else prev) + (1 - ewma_lambda) * prev
        ew[i] = prev
    idx = np.arange(1, len(x) + 1)
    width = ewma_l * sigma * np.sqrt(ewma_lambda / (2 - ewma_lambda) * (1 - (1 - ewma_lambda) ** (2 * idx)))
    return pd.DataFrame(
        {
            "value": x,
            "z": z,
            "centre": centre,
            "sigma": sigma,
            "ucl": centre + 3 * sigma,
            "lcl": centre - 3 * sigma,
            "ewma": ew,
            "ewma_ucl": centre + width,
            "ewma_lcl": centre - width,
            "ewma_signal": (ew > centre + width) | (ew < centre - width),
            **flags,
        }
    )


def changepoints(values: np.ndarray, *, penalty: str | float = "bic", min_size: int = 10) -> list[int]:
    """Indices (exclusive segment ends) of mean shifts detected by PELT on the standardised series."""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2 * min_size:
        return []
    mr = np.abs(np.diff(x))
    sigma = float(np.mean(mr) / 1.128) if len(mr) else float(np.std(x))
    sigma = sigma if sigma > 0 else 1.0
    z = (x - np.median(x)) / sigma
    pen = {"bic": 2.0 * math.log(n), "aic": 2.0}[penalty.lower()] if isinstance(penalty, str) else float(penalty)
    bkps = pelt_l2(z, pen, min_size)
    return [int(b) for b in bkps if b < n]
