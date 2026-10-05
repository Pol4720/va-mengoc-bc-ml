"""Disproportionality analysis for spontaneous AEFI reports.

Frequentist measures (ROR, PRR with Evans' criteria) and Bayesian shrinkage
measures (BCPNN information component, Norén et al. 2013; MGPS empirical
Bayes geometric mean, DuMouchel 1999) are computed on report-level 2×2
tables:

=================  ===========  ===============
                   event        no event
=================  ===========  ===============
target vaccine     a            b
comparator         c            d
=================  ===========  ===============

Disproportionality quantifies *reporting* association, not risk; results are
hypothesis-generating and are reported following READUS-PV
(Fusaroli et al. 2024).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

from vamengoc.analysis.stats_utils import benjamini_hochberg

__all__ = [
    "MGPSPrior",
    "bcpnn_ic",
    "cumulative_ic",
    "disproportionality_table",
    "ebgm",
    "fit_mgps_prior",
    "prr",
    "ror",
    "two_by_two",
]

Z975 = 1.959963984540054


@dataclass(frozen=True)
class TwoByTwo:
    a: int
    b: int
    c: int
    d: int

    @property
    def n(self) -> int:
        return self.a + self.b + self.c + self.d

    @property
    def expected(self) -> float:
        """Expected count of target-event reports under independence."""
        return (self.a + self.b) * (self.a + self.c) / self.n if self.n else math.nan


def two_by_two(target: pd.Series, comparator: pd.Series, event: pd.Series) -> TwoByTwo:
    """Build the table from boolean masks (unknown event status counts as absent)."""
    ev = event.astype("boolean").fillna(False).astype(bool)
    t = target.astype(bool)
    c = comparator.astype(bool)
    return TwoByTwo(a=int((t & ev).sum()), b=int((t & ~ev).sum()), c=int((c & ev).sum()), d=int((c & ~ev).sum()))


def ror(t: TwoByTwo) -> tuple[float, float, float]:
    """Reporting odds ratio with Woolf CI; Haldane–Anscombe 0.5 correction on zero cells."""
    a, b, c, d = (float(x) for x in (t.a, t.b, t.c, t.d))
    if min(a, b, c, d) == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    est = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return est, math.exp(math.log(est) - Z975 * se), math.exp(math.log(est) + Z975 * se)


def prr(t: TwoByTwo) -> tuple[float, float, float, float]:
    """Proportional reporting ratio with CI and Yates-corrected chi-square (Evans 2001)."""
    a, b, c, d = (float(x) for x in (t.a, t.b, t.c, t.d))
    if a == 0 or c == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    est = (a / (a + b)) / (c / (c + d))
    se = math.sqrt(max(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d), 0.0))
    n = t.n
    num = n * (abs(t.a * t.d - t.b * t.c) - n / 2) ** 2
    den = (t.a + t.b) * (t.c + t.d) * (t.a + t.c) * (t.b + t.d)
    chi2 = num / den if den > 0 else 0.0
    return est, math.exp(math.log(est) - Z975 * se), math.exp(math.log(est) + Z975 * se), chi2


def bcpnn_ic(t: TwoByTwo) -> tuple[float, float, float]:
    """Shrunk information component IC = log2((O+0.5)/(E+0.5)) with gamma credibility limits.

    Norén GN, Hopstadius J, Bate A. Stat Methods Med Res 2013;22:57-69.
    """
    o, e = float(t.a), float(t.expected)
    ic = math.log2((o + 0.5) / (e + 0.5))
    lo = math.log2(stats.gamma.ppf(0.025, a=o + 0.5, scale=1.0 / (e + 0.5)))
    hi = math.log2(stats.gamma.ppf(0.975, a=o + 0.5, scale=1.0 / (e + 0.5)))
    return ic, lo, hi


# ---------------------------------------------------------------------------------------
# MGPS (Gamma-Poisson shrinker)
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MGPSPrior:
    alpha1: float
    beta1: float
    alpha2: float
    beta2: float
    p: float
    converged: bool
    loglik: float


def _nb_logpmf(n: np.ndarray, e: np.ndarray, alpha: float, beta: float) -> np.ndarray:
    # xlogy keeps n·log(e/(β+e)) = 0 when n = e = 0 (event never reported).
    return np.asarray(
        special.gammaln(alpha + n)
        - special.gammaln(alpha)
        - special.gammaln(n + 1)
        + alpha * np.log(beta / (beta + e))
        + special.xlogy(n, e / (beta + e))
    )


def fit_mgps_prior(n: np.ndarray, e: np.ndarray, *, starts: list[tuple[float, ...]] | None = None) -> MGPSPrior:
    """Maximum-likelihood two-component gamma mixture prior (DuMouchel 1999)."""
    n = np.asarray(n, dtype=float)
    e = np.asarray(e, dtype=float)
    keep = e > 0
    n, e = n[keep], e[keep]

    def nll(theta: np.ndarray) -> float:
        a1, b1, a2, b2 = np.exp(theta[:4])
        w = 1 / (1 + np.exp(-theta[4]))
        l1 = _nb_logpmf(n, e, a1, b1)
        l2 = _nb_logpmf(n, e, a2, b2)
        ll = np.logaddexp(np.log(w) + l1, np.log1p(-w) + l2)
        val = -float(np.sum(ll))
        return val if np.isfinite(val) else 1e300

    starts = starts or [(0.2, 0.1, 2.0, 4.0, 1 / 3), (0.5, 0.5, 5.0, 5.0, 0.2), (1.0, 1.0, 3.0, 1.0, 0.5)]
    best: optimize.OptimizeResult | None = None
    for s in starts:
        x0 = np.array([*np.log(s[:4]), math.log(s[4] / (1 - s[4]))])
        res = optimize.minimize(
            nll, x0, method="Nelder-Mead", options={"maxiter": 20_000, "xatol": 1e-8, "fatol": 1e-8}
        )
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    a1, b1, a2, b2 = (float(v) for v in np.exp(best.x[:4]))
    w = float(1 / (1 + np.exp(-best.x[4])))
    return MGPSPrior(a1, b1, a2, b2, w, bool(best.success), -float(best.fun))


def _posterior_weight(n: float, e: float, prior: MGPSPrior) -> float:
    l1 = _nb_logpmf(np.array([n]), np.array([e]), prior.alpha1, prior.beta1)[0]
    l2 = _nb_logpmf(np.array([n]), np.array([e]), prior.alpha2, prior.beta2)[0]
    a = math.log(prior.p) + l1
    b = math.log1p(-prior.p) + l2
    return float(math.exp(a - np.logaddexp(a, b)))


def ebgm(n: float, e: float, prior: MGPSPrior) -> tuple[float, float, float]:
    """Empirical Bayes geometric mean and its 5th/95th posterior percentiles (EB05, EB95)."""
    q = _posterior_weight(n, e, prior)
    a1, b1 = prior.alpha1 + n, prior.beta1 + e
    a2, b2 = prior.alpha2 + n, prior.beta2 + e
    elog = q * (special.digamma(a1) - math.log(b1)) + (1 - q) * (special.digamma(a2) - math.log(b2))

    def cdf(x: float) -> float:
        return float(q * stats.gamma.cdf(x, a1, scale=1 / b1) + (1 - q) * stats.gamma.cdf(x, a2, scale=1 / b2))

    def quantile(p: float) -> float:
        lo, hi = 1e-12, 1.0
        while cdf(hi) < p:
            hi *= 2
            if hi > 1e12:  # pragma: no cover - pathological prior
                return math.inf
        return float(optimize.brentq(lambda x: cdf(x) - p, lo, hi, xtol=1e-10))

    return float(math.exp(elog)), quantile(0.05), quantile(0.95)


# ---------------------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------------------
def disproportionality_table(
    reports: pd.DataFrame,
    target_mask: pd.Series,
    comparator_mask: pd.Series,
    events: list[str],
    *,
    prior: MGPSPrior | None = None,
    criteria: dict[str, float] | None = None,
    primary: str = "ic",
    recorded: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """One row per event with every measure and the signal criteria met.

    ``signal_primary`` applies the prespecified criterion (``primary``: ``ic``, ``ror``, ``prr``,
    ``ebgm`` or ``consensus2`` = at least two methods); ``signal_any`` (any method) is reported
    as a sensitivity analysis only. ``recorded`` maps an event to the reports whose form had its
    column; the 2×2 table of that event is built on those reports only.
    """
    crit = {
        "min_reports": 3,
        "ror_lower_threshold": 1.0,
        "prr_threshold": 2.0,
        "prr_chi2_threshold": 4.0,
        "ic025_threshold": 0.0,
        "eb05_threshold": 2.0,
    }
    crit.update(criteria or {})
    rows: list[dict[str, Any]] = []
    for ev in events:
        known = recorded.get(ev) if recorded else None
        if known is None:
            t = two_by_two(target_mask, comparator_mask, reports[ev])
        else:
            t = two_by_two(target_mask & known, comparator_mask & known, reports[ev])
        r, rlo, rhi = ror(t)
        p, plo, phi, chi2 = prr(t)
        ic, iclo, ichi = bcpnn_ic(t)
        fisher_p = float(stats.fisher_exact([[t.a, t.b], [t.c, t.d]])[1]) if t.n else math.nan
        row: dict[str, Any] = {
            "event": ev,
            "a": t.a,
            "b": t.b,
            "c": t.c,
            "d": t.d,
            "expected": t.expected,
            "ror": r,
            "ror_lo": rlo,
            "ror_hi": rhi,
            "prr": p,
            "prr_lo": plo,
            "prr_hi": phi,
            "chi2_yates": chi2,
            "ic": ic,
            "ic025": iclo,
            "ic975": ichi,
            "fisher_p": fisher_p,
        }
        if prior is not None:
            eb, eb05, eb95 = ebgm(t.a, t.expected, prior)
            row.update({"ebgm": eb, "eb05": eb05, "eb95": eb95})
        enough = t.a >= crit["min_reports"]
        row["signal_ror"] = bool(enough and rlo > crit["ror_lower_threshold"])
        row["signal_prr"] = bool(enough and p >= crit["prr_threshold"] and chi2 >= crit["prr_chi2_threshold"])
        row["signal_ic"] = bool(iclo > crit["ic025_threshold"])
        row["signal_ebgm"] = bool(prior is not None and row.get("eb05", 0) >= crit["eb05_threshold"])
        row["signal_any"] = row["signal_ror"] or row["signal_prr"] or row["signal_ic"] or row["signal_ebgm"]
        row["n_criteria_met"] = sum(row[k] for k in ("signal_ror", "signal_prr", "signal_ic", "signal_ebgm"))
        row["signal_primary"] = bool(
            enough and (row["n_criteria_met"] >= 2 if primary == "consensus2" else row[f"signal_{primary}"])
        )
        rows.append(row)
    out = pd.DataFrame.from_records(rows)
    if len(out):
        out["fisher_p_bh"] = benjamini_hochberg(out["fisher_p"].to_numpy())
    return out


def vaccine_event_counts(
    administrations: pd.DataFrame,
    events_long: pd.DataFrame,
    record_ids: pd.Series,
    recorded: dict[str, set[Any]] | None = None,
) -> pd.DataFrame:
    """Counts N_ij (vaccine i, event j) and expected E_ij over all vaccine-event pairs.

    Reports with several vaccines contribute to each of them (standard practice
    for suspected products); the expected count uses the report totals. With ``recorded``
    (event -> record ids whose form had the event's column) each event is counted, and its
    expected values computed, on those reports only.
    """
    if recorded is not None:
        parts = []
        for event in sorted(events_long["event"].unique()):
            ids = pd.Series(sorted(set(record_ids) & recorded.get(event, set())), dtype=object)
            if ids.empty:
                continue
            sub = vaccine_event_counts(administrations, events_long[events_long["event"] == event], ids)
            parts.append(sub[sub["event"] == event])
        return (
            pd.concat(parts, ignore_index=True)
            if parts
            else vaccine_event_counts(administrations, events_long, record_ids)
        )
    keep = set(record_ids)
    adm = administrations[administrations["record_id"].isin(keep)][["record_id", "vaccine"]].drop_duplicates()
    ev = events_long[events_long["record_id"].isin(keep) & events_long["present"].fillna(False)]
    pairs = adm.merge(ev[["record_id", "event"]], on="record_id")
    n_ij = pairs.groupby(["vaccine", "event"]).size().rename("n")
    n_i = adm.groupby("vaccine").size()
    n_j = ev.groupby("event").size()
    total = len(keep)
    grid = pd.MultiIndex.from_product([n_i.index, sorted(events_long["event"].unique())], names=["vaccine", "event"])
    out = n_ij.reindex(grid, fill_value=0).reset_index()
    out["n_vaccine"] = out["vaccine"].map(n_i)
    out["n_event"] = out["event"].map(n_j).fillna(0)
    out["expected"] = out["n_vaccine"] * out["n_event"] / total
    return out


def cumulative_ic(
    reports: pd.DataFrame,
    target_mask: pd.Series,
    comparator_mask: pd.Series,
    event: str,
    years: list[int],
    recorded: pd.Series | None = None,
) -> pd.DataFrame:
    """IC and its credibility interval recomputed on data accumulated up to each year.

    ``recorded`` restricts the accumulation to reports whose form had the event's column.
    """
    rows = []
    for y in years:
        upto = reports["analytic_year"] <= y
        if recorded is not None:
            upto = upto & recorded
        t = two_by_two(target_mask & upto, comparator_mask & upto, reports[event])
        ic, lo, hi = bcpnn_ic(t)
        rows.append({"event": event, "year": y, "a": t.a, "expected": t.expected, "ic": ic, "ic025": lo, "ic975": hi})
    return pd.DataFrame.from_records(rows)
