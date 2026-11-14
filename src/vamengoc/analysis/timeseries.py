"""Temporal analyses: monthly reporting series and the national incidence context.

* Monthly AEFI report counts are variance-stabilised (Anscombe transform) and
  scanned for mean shifts with PELT — this documents disruptions of the
  surveillance system (e.g. the COVID-19 period) that condition every
  temporal comparison.
* The 1970–2024 meningococcal-disease series is summarised with a segmented
  (interrupted time-series) negative-binomial regression around the national
  vaccination campaign. It is ecological context only: it cannot attribute
  the decline to the vaccine.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from vamengoc.analysis.changepoint import pelt_l2

__all__ = ["incidence_its", "monthly_changepoints", "monthly_series"]


def monthly_series(
    reports: pd.DataFrame, mask: pd.Series | None = None, coverage: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Counts per calendar month of vaccination (complete month grid).

    With ``coverage`` (from :func:`vamengoc.curate.rules.month_coverage`), months that no
    workbook covers (2023 after July, the months of the current year not yet delivered) are
    returned as missing (``count`` NA, ``observed`` False) rather than as zero.
    """
    d = reports if mask is None else reports[mask]
    d = d.dropna(subset=["vaccination_date"])
    if d.empty:
        return pd.DataFrame(columns=["month", "count", "observed"])
    per = d["vaccination_date"].dt.to_period("M")
    counts = per.value_counts().sort_index()
    full = pd.period_range(counts.index.min(), counts.index.max(), freq="M")
    counts = counts.reindex(full, fill_value=0)
    observed = pd.Series(True, index=full)
    if coverage is not None and not coverage.empty:
        cov = {(int(r.year), int(r.month)): bool(r.observed) for r in coverage.itertuples(index=False)}
        years = {y for y, _ in cov}
        # A month is missing only when its year has a workbook that does not cover it; months of
        # years without a workbook (late reports of an earlier year) keep their counts.
        observed = pd.Series([cov.get((p.year, p.month), p.year not in years) for p in full], index=full)
    out = pd.DataFrame(
        {
            "month": full.astype(str),
            "count": pd.array(np.where(observed, counts.to_numpy(dtype=int), 0), dtype="Int64"),
            "observed": observed.to_numpy(dtype=bool),
        }
    )
    out.loc[~out["observed"], "count"] = pd.NA
    # Trim leading/trailing unobserved months (the series starts and ends with data).
    obs_idx = np.flatnonzero(out["observed"].to_numpy())
    if len(obs_idx):
        out = out.iloc[obs_idx[0] : obs_idx[-1] + 1].reset_index(drop=True)
    return out


def monthly_changepoints(series: pd.DataFrame, *, min_size: int = 6) -> dict[str, Any]:
    """PELT on the Anscombe-transformed monthly counts (unit variance; BIC-type penalty).

    Unobserved months are left out (the series is scanned over the observed months in order).
    """
    if "observed" in series:
        series = series[series["observed"].astype(bool)].reset_index(drop=True)
    y = series["count"].to_numpy(dtype=float)
    n = len(y)
    if n < 2 * min_size:
        return {"n_months": n, "breaks": [], "segments": []}
    z = 2 * np.sqrt(y + 3 / 8)
    pen = 2.0 * math.log(n) * float(np.var(np.diff(z)) / 2 or 1.0)
    bkps = pelt_l2(z, pen, min_size)
    segments = []
    start = 0
    for b in bkps:
        seg = y[start:b]
        segments.append(
            {
                "start": series["month"].iloc[start],
                "end": series["month"].iloc[b - 1],
                "months": b - start,
                "mean_count": float(seg.mean()),
            }
        )
        start = b
    return {
        "n_months": n,
        "breaks": [series["month"].iloc[b] for b in bkps if b < n],
        "segments": segments,
        "penalty": pen,
    }


def incidence_its(
    incidence: pd.DataFrame, *, intervention_year: int = 1989, end_transition: int = 1991
) -> dict[str, Any]:
    """Segmented regression of annual cases: pre-trend, level and slope change.

    Transition years (``intervention_year`` … ``end_transition``) are modelled
    by their own indicator so that the post-period slope is not distorted by
    the roll-out.
    """
    d = incidence.dropna(subset=["cases"]).copy()
    d = d[d["cases"] >= 0]
    t = d["year"].astype(float) - intervention_year
    post = (d["year"] > end_transition).astype(float)
    transition = d["year"].between(intervention_year, end_transition).astype(float)
    x = pd.DataFrame(
        {
            "const": 1.0,
            "time": t,
            "transition": transition,
            "post": post,
            "time_post": (d["year"].astype(float) - end_transition) * post,
        }
    )
    y = d["cases"].astype(float)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        nb = sm.NegativeBinomial(y.to_numpy(), x.to_numpy()).fit(disp=0, maxiter=500)
    params = pd.Series(nb.params[: x.shape[1]], index=x.columns)
    bse = pd.Series(nb.bse[: x.shape[1]], index=x.columns)

    def rr(name: str) -> dict[str, float]:
        b, s = float(params[name]), float(bse[name])
        return {"rr": math.exp(b), "lo": math.exp(b - 1.96 * s), "hi": math.exp(b + 1.96 * s)}

    pre = d[d["year"] < intervention_year]
    postd = d[d["year"] > end_transition]
    fitted = np.asarray(nb.predict(x.to_numpy()))
    return {
        "n_years": len(d),
        "intervention_year": intervention_year,
        "end_transition": end_transition,
        "pre_trend_rr_per_year": rr("time"),
        "level_change_rr": rr("post"),
        "post_trend_rr_per_year": {"rr": math.exp(float(params["time"] + params["time_post"]))},
        "slope_change_rr": rr("time_post"),
        "mean_rate_pre": float(pre["incidence_rate"].mean()) if "incidence_rate" in pre else math.nan,
        "mean_rate_post": float(postd["incidence_rate"].mean()) if "incidence_rate" in postd else math.nan,
        "alpha": float(nb.params[-1]),
        "fitted": pd.DataFrame({"year": d["year"].astype(int).to_numpy(), "cases": y.to_numpy(), "fitted": fitted}),
    }


def cooccurrence(reports: pd.DataFrame, events: list[str], min_prevalence: float = 0.01) -> pd.DataFrame:
    """Pairwise log odds ratios (Haldane-corrected) between event indicators."""
    x = reports[events].astype("boolean").fillna(False).astype(bool)
    keep = [e for e in events if x[e].mean() >= min_prevalence]
    rows = []
    for i, a in enumerate(keep):
        for b in keep[i + 1 :]:
            n11 = int((x[a] & x[b]).sum()) + 0.5
            n10 = int((x[a] & ~x[b]).sum()) + 0.5
            n01 = int((~x[a] & x[b]).sum()) + 0.5
            n00 = int((~x[a] & ~x[b]).sum()) + 0.5
            lor = math.log(n11 * n00 / (n10 * n01))
            se = math.sqrt(1 / n11 + 1 / n10 + 1 / n01 + 1 / n00)
            rows.append(
                {
                    "event_a": a,
                    "event_b": b,
                    "n_both": int(n11 - 0.5),
                    "log_or": lor,
                    "lo": lor - 1.96 * se,
                    "hi": lor + 1.96 * se,
                }
            )
    return pd.DataFrame.from_records(rows)
