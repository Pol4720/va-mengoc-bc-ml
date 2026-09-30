"""Statistical models recover planted truths on simulated data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import ruptures as rpt

from vamengoc.analysis import lca, rates, spc
from vamengoc.analysis.changepoint import pelt_l2
from vamengoc.analysis.equivalence import energy_test, hodges_lehmann, tost_welch
from vamengoc.analysis.mspc import fit_mspc, flagged_summary, top_contributors
from vamengoc.analysis.stats_utils import benjamini_hochberg, expit, logit, poisson_exact_ci, wilson_ci
from vamengoc.parsing.specs import Spec


def test_poisson_and_wilson() -> None:
    assert poisson_exact_ci(0) == (0.0, pytest.approx(3.688879, rel=1e-5))
    lo, hi = poisson_exact_ci(10)
    assert lo == pytest.approx(4.795389, rel=1e-5) and hi == pytest.approx(18.390356, rel=1e-5)
    with pytest.raises(ValueError, match="non-negative"):
        poisson_exact_ci(-1)
    lo, hi = wilson_ci(5, 10)
    assert lo < 0.5 < hi
    assert np.isnan(wilson_ci(0, 0)[0])
    adj = benjamini_hochberg([0.01, 0.04, np.nan, 0.03])
    assert np.isnan(adj[2]) and adj[0] == pytest.approx(0.03) and adj[1] == pytest.approx(0.04)
    assert np.all(np.isnan(benjamini_hochberg([np.nan])))
    assert float(expit(logit(0.3))) == pytest.approx(0.3)


def test_rates_and_trend() -> None:
    counts = pd.DataFrame({"analytic_year": [2017, 2018, 2019, 2020], "n": [100, 110, 121, 50]})
    doses = pd.DataFrame({"year": [2017, 2018, 2019], "doses_administered": [1e5, 1e5, 1e5]})
    r = rates.annual_reporting_rates(counts, doses, count_col="n", expected_rate=50)
    assert r.loc[0, "rate_per_100k"] == pytest.approx(100)
    assert r.loc[0, "ratio_to_expected"] == pytest.approx(2)
    assert np.isnan(r.loc[3, "rate_per_100k"])
    t = rates.rate_trend(r)
    assert t["estimable"] and t["rr_per_year"] == pytest.approx(1.1, rel=1e-3)
    assert rates.rate_trend(r.head(2))["estimable"] is False


def test_pelt_matches_ruptures() -> None:
    rng = np.random.default_rng(0)
    for _ in range(40):
        n = int(rng.integers(30, 150))
        x = rng.normal(size=n)
        x[n // 2 :] += 2.5
        ms = int(rng.integers(2, 8))
        pen = float(rng.uniform(2, 15))
        mine = pelt_l2(x, pen, ms)
        ref = rpt.Pelt(model="l2", min_size=ms, jump=1).fit(x.reshape(-1, 1)).predict(pen=pen)

        def cost(bk: list[int], x: np.ndarray = x, pen: float = pen) -> float:
            s, tot = 0, 0.0
            for e in bk:
                seg = x[s:e]
                tot += float(((seg - seg.mean()) ** 2).sum())
                s = e
            return tot + pen * (len(bk) - 1)

        assert cost(mine) == pytest.approx(cost(ref), abs=1e-8)
    assert pelt_l2(np.array([]), 1.0) == []
    assert pelt_l2(np.ones(3), 1.0, 2) == [3]


def test_spc_scales_capability_charts() -> None:
    rng = np.random.default_rng(1)
    lots = pd.DataFrame(
        {
            "ph": rng.normal(6.6, 0.1, 400),
            "endotoxin": np.exp(rng.normal(8, 0.4, 400)),
            "igg_elisa": np.exp(rng.normal(10, 0.3, 400)),
        }
    )
    specs = {
        "ph": Spec("range", 6.0, 7.2),
        "endotoxin": Spec("le", high=20000),
        "igg_elisa": Spec("ge", 7000),
        "qual": Spec("qualitative"),
    }
    schema = {"transforms": {"endotoxin": "log10p1", "igg_elisa": "log10"}, "natural_bounds": {"endotoxin": {"low": 0}}}
    sc = spc.attribute_scales(specs, lots, schema)
    assert set(sc) == {"ph", "endotoxin", "igg_elisa"}
    assert sc["endotoxin"].one_sided == "upper" and sc["endotoxin"].window_low == 0
    assert sc["igg_elisa"].one_sided == "lower" and sc["igg_elisa"].low == pytest.approx(np.log10(7000))
    w = spc.to_window(np.array([6.0, 6.6, 7.2]), sc["ph"])
    assert w == pytest.approx([0, 0.5, 1])
    cap = spc.capability(lots["ph"].to_numpy(), sc["ph"], n_boot=200, seed=0)
    expected = min(6.6 - 6.0, 7.2 - 6.6) / (3 * 0.1)
    assert cap["ppk"] == pytest.approx(expected, rel=0.15)
    assert cap["ppk_lo"] < cap["ppk"] < cap["ppk_hi"] and cap["pct_conforming"] == 100
    assert spc.capability(np.array([1.0, 2.0]), sc["ph"])["estimable"] is False
    x = rng.normal(0, 1, 200)
    x[150] = 8  # rule 1
    ch = spc.control_chart(x)
    assert ch.loc[150, "rule1"] and ch["rule1"].sum() >= 1
    trend = np.arange(30, dtype=float) * 0.5
    assert spc.control_chart(trend)["rule3"].any()
    assert spc.control_chart(
        np.r_[np.zeros(20), np.ones(20) * 3], baseline=np.r_[np.ones(20, bool), np.zeros(20, bool)]
    )["ewma_signal"].any()
    shift = np.r_[rng.normal(0, 1, 100), rng.normal(2, 1, 100)]
    cps = spc.changepoints(shift, penalty="bic", min_size=10)
    assert cps and abs(cps[0] - 100) <= 5
    assert spc.changepoints(shift[:10]) == []
    assert spc.changepoints(rng.normal(0, 1, 300), penalty=50.0) == []


def test_mspc_flags_outliers() -> None:
    rng = np.random.default_rng(2)
    cov = np.array([[1, 0.8, 0], [0.8, 1, 0], [0, 0, 1]])
    x = rng.multivariate_normal(np.zeros(3), cov, 300)
    x[0] = [3, -3, 0]  # breaks the correlation structure -> SPE / T2
    x[1] = [6, 6, 0]  # extreme but correlated -> T2
    df = pd.DataFrame(x, columns=["a", "b", "c"], index=[f"L{i}" for i in range(300)])
    df.iloc[5, 0] = np.nan
    res = fit_mspc(df, alpha=0.01, variance_target=0.6)
    assert res.notes
    assert res.scores.loc["L0", "spe_flag"] or res.scores.loc["L0", "t2_flag"]
    assert res.scores.loc["L1", "t2_flag"]
    assert res.scores["t2_flag"].mean() < 0.08
    summ = flagged_summary(res, pd.Series(2011 + np.arange(300) % 5, index=df.index))
    assert summ["n_lots"].sum() == 299
    assert top_contributors(res)["n_flagged"] >= 2


def test_equivalence_and_energy() -> None:
    rng = np.random.default_rng(4)
    a, b = rng.normal(0.5, 0.1, 200), rng.normal(0.5, 0.1, 300)
    t = tost_welch(a, b, margin=0.1)
    assert t["equivalent"] and t["ci90_lo"] < 0 < t["ci90_hi"]
    t2 = tost_welch(a, b + 0.2, margin=0.1)
    assert not t2["equivalent"]
    assert tost_welch(a[:2], b, 0.1)["estimable"] is False
    hl = hodges_lehmann(a, b + 0.1)
    assert hl["lo"] < hl["shift"] < hl["hi"] and hl["shift"] == pytest.approx(-0.1, abs=0.03)
    e_same = energy_test(rng.normal(0, 1, (60, 2)), rng.normal(0, 1, (80, 2)), n_perm=99, seed=1)
    e_diff = energy_test(rng.normal(0, 1, (60, 2)), rng.normal(1, 1, (80, 2)), n_perm=99, seed=1)
    assert e_diff["p_value"] < 0.05 < e_same["p_value"]


def test_lca_recovers_two_classes() -> None:
    rng = np.random.default_rng(5)
    n = 1500
    z = rng.random(n) < 0.35
    probs = np.where(z[:, None], [0.9, 0.8, 0.1, 0.1, 0.2], [0.1, 0.15, 0.85, 0.7, 0.2])
    x = (rng.random((n, 5)) < probs).astype(float)
    x[rng.random((n, 5)) < 0.02] = np.nan  # missing at random
    df = pd.DataFrame(x, columns=list("abcde"))
    sel = lca.select_lca(df, (1, 4), n_starts=5, seed=0, bootstrap=3)
    assert sel["best_k"] == 2
    fit = sel["fit"]
    assert fit.weights[0] == pytest.approx(0.65, abs=0.05)
    assert fit.theta[0, 2] == pytest.approx(0.85, abs=0.07)
    assert fit.entropy_r2 > 0.5 and np.isfinite(fit.icl_bic) and fit.aic < fit.bic
    assert sel["bootstrap_ari_median"] > 0.8
    prof = lca.class_profiles(fit, list("abcde"))
    assert len(prof) == 10
    one = lca.fit_lca(df, 1, n_starts=1)
    assert one.entropy_r2 == 1.0


def test_calibration_degenerate_predictions() -> None:
    from vamengoc.analysis.seriousness import _calibration, _metrics

    y = np.array([0, 0, 1, 0, 1, 0])
    icpt, slope = _calibration(y, np.full(6, 0.3))
    assert np.isfinite(icpt) and np.isnan(slope)
    m = _metrics(np.zeros(5), np.full(5, 0.1))
    assert np.isnan(m["auroc"]) and m["prevalence"] == 0.0


def test_dose_category_collapses_combinations() -> None:
    from vamengoc.analysis.descriptive import dose_category

    s = pd.Series(["1", "2", "3", "R", "U", "R|1", "1|1", None, "X", float("nan")])
    out = dose_category(s).tolist()
    assert out[:7] == ["1", "2", "3", "R", "U", "multiple", "multiple"]
    assert out[7] is None and out[8] == "other" and pd.isna(out[9])


def test_firth_matches_haldane_on_two_by_two_and_handles_separation() -> None:
    from vamengoc.analysis.stats_utils import drop_collinear_columns, firth_logit

    # Saturated 2x2 model: Firth estimate of the log OR equals the Haldane-corrected log OR.
    a, b, c, d = 12, 30, 4, 60  # exposed cases, exposed non-cases, unexposed cases, unexposed non-cases
    xe = np.r_[np.ones(a + b), np.zeros(c + d)]
    y = np.r_[np.ones(a), np.zeros(b), np.ones(c), np.zeros(d)]
    res = firth_logit(np.column_stack([np.ones_like(xe), xe]), y)
    assert res.converged
    expected = np.log((a + 0.5) * (d + 0.5) / ((b + 0.5) * (c + 0.5)))
    assert res.params[1] == pytest.approx(expected, abs=1e-6)
    lo, hi = res.conf_int()[1]
    assert lo < res.params[1] < hi and 0 <= res.pvalues()[1] <= 1
    # Complete separation: maximum likelihood diverges, Firth stays finite.
    xs = np.r_[np.ones(10), np.zeros(40)]
    ys = np.r_[np.ones(10), np.zeros(40)]
    sep = firth_logit(np.column_stack([np.ones_like(xs), xs]), ys)
    assert np.isfinite(sep.params).all() and sep.params[1] > 2
    # Collinearity helper keeps the first of two identical columns.
    x = np.column_stack([np.ones(5), [1, 0, 1, 0, 1], [1, 0, 1, 0, 1], [0, 1, 0, 1, 0]])
    keep, dropped = drop_collinear_columns(x, ["c", "a", "a2", "b"])
    assert keep == [0, 1] and dropped == ["a2", "b"]
