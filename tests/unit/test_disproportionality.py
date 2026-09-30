"""Disproportionality measures against hand calculations and known behaviour."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from vamengoc.analysis import disproportionality as dp


def test_two_by_two_and_measures() -> None:
    t = dp.TwoByTwo(a=20, b=80, c=100, d=900)
    assert t.n == 1100 and t.expected == pytest.approx(100 * 120 / 1100)
    r, lo, hi = dp.ror(t)
    assert r == pytest.approx((20 * 900) / (80 * 100))
    se = math.sqrt(1 / 20 + 1 / 80 + 1 / 100 + 1 / 900)
    assert lo == pytest.approx(r * math.exp(-1.959964 * se), rel=1e-6)
    assert hi == pytest.approx(r * math.exp(1.959964 * se), rel=1e-6)
    p, plo, phi, chi2 = dp.prr(t)
    assert p == pytest.approx((20 / 100) / (100 / 1000))
    assert plo < p < phi
    # Yates chi-square equals scipy's corrected statistic
    assert chi2 == pytest.approx(stats.chi2_contingency([[20, 80], [100, 900]], correction=True)[0])
    ic, iclo, ichi = dp.bcpnn_ic(t)
    assert ic == pytest.approx(math.log2((20 + 0.5) / (t.expected + 0.5)))
    assert iclo < ic < ichi


def test_zero_cells_are_finite() -> None:
    t = dp.TwoByTwo(a=0, b=50, c=10, d=500)
    r, lo, hi = dp.ror(t)
    assert all(np.isfinite([r, lo, hi]))
    p, plo, phi, chi2 = dp.prr(t)
    assert all(np.isfinite([p, plo, phi, chi2]))
    ic, iclo, _ = dp.bcpnn_ic(t)
    assert ic < 0 and iclo < ic


def test_two_by_two_from_masks() -> None:
    df = pd.DataFrame({"t": [True, True, False, False, False], "ev": [True, None, True, False, False]})
    t = dp.two_by_two(df["t"], ~df["t"], df["ev"])
    assert (t.a, t.b, t.c, t.d) == (1, 1, 1, 2)


def _simulate_counts(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    e = rng.gamma(2.0, 2.0, size=600)
    lam = np.where(rng.random(600) < 0.8, rng.gamma(20, 1 / 20, 600), rng.gamma(2, 1.0, 600))
    return rng.poisson(lam * e), e


def test_mgps_fit_and_shrinkage() -> None:
    rng = np.random.default_rng(3)
    n, e = _simulate_counts(rng)
    prior = dp.fit_mgps_prior(n, e)
    assert prior.converged and 0 < prior.p < 1
    # EBGM shrinks a small observed/expected ratio towards the prior mean ...
    eb_small, eb05, eb95 = dp.ebgm(3, 0.5, prior)
    assert eb05 < eb_small < eb95
    assert eb_small < 3 / 0.5
    # ... but tracks it closely with large counts.
    eb_big, *_ = dp.ebgm(600, 100.0, prior)
    assert eb_big == pytest.approx(6.0, rel=0.1)
    # zero expected count (event never reported) is handled
    assert np.isfinite(dp.ebgm(0, 0.0, prior)[0])


def test_table_signals() -> None:
    rng = np.random.default_rng(1)
    n = 4000
    target = rng.random(n) < 0.2
    p = np.where(target, 0.25, 0.1)  # event over-reported with the target
    df = pd.DataFrame(
        {
            "t": target,
            "ev_x": rng.random(n) < p,
            "ev_null": rng.random(n) < 0.1,
            "analytic_year": rng.integers(2017, 2020, n),
        }
    )
    out = dp.disproportionality_table(df, df["t"], ~df["t"], ["ev_x", "ev_null"])
    x = out.set_index("event").loc["ev_x"]
    assert x["signal_ror"] and x["signal_ic"] and x["ror_lo"] > 1
    null = out.set_index("event").loc["ev_null"]
    assert not null["signal_prr"]
    assert "fisher_p_bh" in out and out["fisher_p_bh"].between(0, 1).all()
    cum = dp.cumulative_ic(df, df["t"], ~df["t"], "ev_x", [2017, 2018, 2019])
    assert list(cum["a"]) == sorted(cum["a"])  # accumulates


def test_vaccine_event_counts() -> None:
    adm = pd.DataFrame({"record_id": ["r1", "r1", "r2", "r3"], "vaccine": ["A", "B", "A", "B"]})
    ev = pd.DataFrame(
        {"record_id": ["r1", "r1", "r2", "r3"], "event": ["e1", "e2", "e1", "e2"], "present": [True, False, True, True]}
    )
    out = dp.vaccine_event_counts(adm, ev, pd.Series(["r1", "r2", "r3"]))
    got = out.set_index(["vaccine", "event"])["n"].to_dict()
    assert got[("A", "e1")] == 2 and got[("B", "e1")] == 1 and got[("B", "e2")] == 1 and got[("A", "e2")] == 0
    assert out["expected"].sum() == pytest.approx((out["n_vaccine"] * out["n_event"] / 3).sum())


@pytest.mark.parametrize("primary", ["ic", "ror", "prr", "ebgm", "consensus2"])
def test_primary_signal_criterion(primary: str) -> None:
    rng = np.random.default_rng(3)
    n = 4000
    target = pd.Series(rng.random(n) < 0.2)
    ev = pd.Series(np.where(target, rng.random(n) < 0.30, rng.random(n) < 0.05))
    reports = pd.DataFrame({"ev_x": ev.astype(int)})
    tab = dp.disproportionality_table(reports, target, ~target, ["ev_x"], primary=primary)
    row = tab.iloc[0]
    expected = row["n_criteria_met"] >= 2 if primary == "consensus2" else row[f"signal_{primary}"]
    assert bool(row["signal_primary"]) == bool(expected)
    if primary != "ebgm":
        assert bool(row["signal_primary"])
