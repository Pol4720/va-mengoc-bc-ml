"""Reporting rates per 100 000 doses administered and their temporal trend.

Passive-surveillance counts divided by doses administered are *reporting*
rates, not incidence: they depend on reporting completeness, which is unknown.
Trends are estimated with a Poisson GLM with log(doses) offset and Pearson
(quasi-Poisson) dispersion, and checked against a negative-binomial fit.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from vamengoc.analysis.stats_utils import poisson_exact_ci

__all__ = ["annual_reporting_rates", "rate_trend"]

PER = 100_000.0


def annual_reporting_rates(
    counts: pd.DataFrame, doses: pd.DataFrame, *, count_col: str, expected_rate: float | None = None
) -> pd.DataFrame:
    """Join annual counts with doses administered and compute exact-CI rates.

    ``counts`` needs ``analytic_year`` and ``count_col``; ``doses`` needs ``year``
    and ``doses_administered``. Years without doses are kept with NaN rates.
    """
    d = counts[["analytic_year", count_col]].rename(columns={"analytic_year": "year", count_col: "count"})
    d = d.merge(doses[["year", "doses_administered"]], on="year", how="left")
    rows = []
    for r in d.itertuples(index=False):
        k = int(r.count)
        dose = float(r.doses_administered) if pd.notna(r.doses_administered) else np.nan
        lo, hi = poisson_exact_ci(k)
        rate = k / dose * PER if dose and not np.isnan(dose) else np.nan
        rows.append(
            {
                "year": int(r.year),
                "count": k,
                "doses": dose,
                "rate_per_100k": rate,
                "rate_lo": lo / dose * PER if dose and not np.isnan(dose) else np.nan,
                "rate_hi": hi / dose * PER if dose and not np.isnan(dose) else np.nan,
                "ratio_to_expected": rate / expected_rate if expected_rate and not np.isnan(rate) else np.nan,
            }
        )
    return pd.DataFrame.from_records(rows)


def rate_trend(rates: pd.DataFrame) -> dict[str, Any]:
    """Annual rate ratio (per year) from quasi-Poisson and negative-binomial models with a dose offset.

    Numerical warnings (e.g. a perfect fit) are captured and reported in the
    output instead of being raised.
    """
    d = rates.dropna(subset=["doses"]).copy()
    d = d[d["doses"] > 0]
    if len(d) < 3:
        return {"n_years": len(d), "estimable": False}
    x = sm.add_constant(d["year"].to_numpy(dtype=float) - d["year"].min())
    y = d["count"].to_numpy(dtype=float)
    doses = d["doses"].to_numpy(dtype=float)
    off = np.log(doses)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        pois = sm.GLM(y, x, family=sm.families.Poisson(), offset=off).fit(scale="X2")
        nb_ok = True
        try:
            nb = sm.NegativeBinomial(y, x, exposure=doses).fit(disp=0, maxiter=500)
        except (ValueError, np.linalg.LinAlgError):  # pragma: no cover - degenerate data
            nb_ok = False
    b, se = float(pois.params[1]), float(pois.bse[1])
    out: dict[str, Any] = {
        "estimable": True,
        "n_years": len(d),
        "first_year": int(d["year"].min()),
        "last_year": int(d["year"].max()),
        "rr_per_year": float(np.exp(b)),
        "rr_lo": float(np.exp(b - 1.959964 * se)),
        "rr_hi": float(np.exp(b + 1.959964 * se)),
        "p_value": float(pois.pvalues[1]),
        "dispersion": float(pois.scale),
        "pooled_rate_per_100k": float(y.sum() / doses.sum() * PER),
        "warnings": sorted({str(w.message)[:160] for w in caught}),
    }
    lo, hi = poisson_exact_ci(int(y.sum()))
    out["pooled_rate_lo"] = float(lo / doses.sum() * PER)
    out["pooled_rate_hi"] = float(hi / doses.sum() * PER)
    if nb_ok and np.all(np.isfinite(nb.params)) and np.all(np.isfinite(nb.bse)):
        out["nb_rr_per_year"] = float(np.exp(nb.params[1]))
        out["nb_rr_lo"] = float(np.exp(nb.params[1] - 1.959964 * nb.bse[1]))
        out["nb_rr_hi"] = float(np.exp(nb.params[1] + 1.959964 * nb.bse[1]))
        out["nb_alpha"] = float(nb.params[-1])
    else:
        out["nb_rr_per_year"] = float("nan")
    return out
