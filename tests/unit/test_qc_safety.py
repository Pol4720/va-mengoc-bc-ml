"""Quality-safety models recover a planted lot effect and stay null otherwise."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vamengoc.analysis import qc_safety as qs
from vamengoc.analysis.spc import attribute_scales
from vamengoc.parsing.specs import Spec

SPECS = {"endotoxin": Spec("le", high=20000), "aloh3_conc": Spec("range", 3, 5), "fill_volume": Spec("ge", 0.5)}
SCHEMA = {"transforms": {"endotoxin": "log10p1"}, "natural_bounds": {"endotoxin": {"low": 0}}}


def _simulate(
    n_lots: int = 120, per_lot: int = 60, log_or: float = np.log(1.6), seed: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    log_e = rng.normal(8.0, 0.5, n_lots)
    lots = pd.DataFrame(
        {
            "lot_key": [f"L{i}" for i in range(n_lots)],
            "endotoxin": np.exp(log_e),
            "aloh3_conc": rng.normal(4, 0.3, n_lots),
            "fill_volume": rng.uniform(0.5, 0.6, n_lots),
            "national": True,
            "production_year": 2016,
        }
    )
    z = (np.log10(1 + lots["endotoxin"]) - np.log10(1 + lots["endotoxin"]).mean()) / np.log10(
        1 + lots["endotoxin"]
    ).std(ddof=1)
    lot_re = rng.normal(0, 0.2, n_lots)
    rows, links = [], []
    k = 0
    for i in range(n_lots):
        for _ in range(per_lot):
            age = rng.choice([3.0, 5.0])
            eta = -0.3 + log_or * z.iloc[i] + lot_re[i] + 0.1 * (age == 5.0)
            y = rng.random() < 1 / (1 + np.exp(-eta))
            rid = f"R{k}"
            k += 1
            rows.append(
                {
                    "record_id": rid,
                    "age_months": age,
                    "sex": rng.choice(["M", "F"]),
                    "target_dose_number": 1 if age == 3.0 else 2,
                    "coadministered": rng.random() < 0.05,
                    "analytic_year": int(rng.integers(2017, 2022)),
                    "ev_fever_39": bool(y),
                    "ev_null": bool(rng.random() < 0.3),
                }
            )
            links.append(
                {"record_id": rid, "lot_key": lots.loc[i, "lot_key"], "match_level": "exact", "temporal_ok": True}
            )
    reports = pd.DataFrame(rows)
    reports["target_dose_number"] = reports["target_dose_number"].astype("Int64")
    return reports, pd.DataFrame(links), lots


@pytest.fixture(scope="module")
def planted() -> qs.QCSafetyFrame:
    reports, links, lots = _simulate()
    scales = attribute_scales(SPECS, lots, SCHEMA)
    atyp = pd.Series(np.random.default_rng(1).gamma(2, 2, len(lots)), index=lots["lot_key"])
    return qs.build_qc_safety_frame(
        reports,
        links,
        lots,
        scales,
        ["endotoxin", "aloh3_conc", "fill_volume", "atypicality_t2", "missing_attr"],
        atypicality=atyp,
    )


def test_frame(planted: qs.QCSafetyFrame) -> None:
    assert planted.n_lots == 120
    assert set(planted.exposures) == {"z_endotoxin", "z_aloh3_conc", "z_fill_volume", "z_atypicality_t2"}
    assert any("missing_attr" in n for n in planted.notes)
    lot_z = planted.data.groupby("lot_key")["z_endotoxin"].first()
    assert lot_z.std(ddof=1) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("cov", ["exchangeable", "independence"])
def test_gee_recovers_planted_effect(planted: qs.QCSafetyFrame, cov: str) -> None:
    out = qs.gee_family(
        planted,
        ["ev_fever_39", "ev_null"],
        cov_struct=cov,
        negative_controls=["fill_volume"],
        adjust_set=["endotoxin", "aloh3_conc"],
    )
    endo = out[(out.outcome == "ev_fever_39") & (out.exposure == "endotoxin") & (out.model == "single")].iloc[0]
    assert endo["or_lo"] < 1.6 < endo["or_hi"]
    assert endo["p_bh"] < 0.01
    fill = out[(out.outcome == "ev_fever_39") & (out.exposure == "fill_volume")].iloc[0]
    assert bool(fill["negative_control"]) and np.isnan(fill["p_bh"])
    null = out[(out.outcome == "ev_null") & (out.model == "single") & (out.exposure == "endotoxin")].iloc[0]
    assert null["or_lo"] < 1 < null["or_hi"]
    assert (out["model"] == "mutually_adjusted").any()


def test_gee_skips_rare_outcome(planted: qs.QCSafetyFrame) -> None:
    d = planted.data.copy()
    d["ev_rare"] = False
    d.loc[d.index[:3], "ev_rare"] = True
    frame = qs.QCSafetyFrame(d, planted.exposures, planted.exposure_sd, planted.covariate_terms, planted.n_lots)
    out = qs.gee_family(frame, ["ev_rare"])
    assert out.iloc[0]["model"] == "skipped"


def test_mixed_lot_level_mde_incremental(planted: qs.QCSafetyFrame) -> None:
    mm = qs.mixed_model_sensitivity(planted, ["ev_fever_39"])
    endo = mm[mm.exposure == "endotoxin"].iloc[0]
    assert endo["cri_lo"] > 1.0
    ll = qs.lot_level_models(planted, ["ev_fever_39"])
    ll_endo = ll[ll.exposure == "endotoxin"].iloc[0]
    assert ll_endo["or_per_sd"] > 1.2
    # Binomial sampling only: the Pearson dispersion must be close to 1 on the count scale.
    assert 0.5 < ll_endo["dispersion"] < 2.0
    assert ll_endo["or_hi"] / ll_endo["or_lo"] > 1.05
    mde = qs.minimum_detectable_or(planted, "ev_fever_39")
    assert 1.0 < mde["mde_or_per_sd"] < 1.6 and mde["design_effect"] >= 1
    inc = qs.incremental_value(planted, "ev_fever_39", folds=3, n_perm=9, seed=0)
    assert inc["estimable"] and inc["delta_auc"] > 0.03 and inc["perm_p"] <= 0.1
    inc_null = qs.incremental_value(planted, "ev_null", folds=3, n_perm=9, seed=0)
    assert inc_null["perm_p"] > 0.1


def test_icc_and_mde_edge_cases() -> None:
    y = pd.Series([0, 1, 0, 1, 0, 1])
    assert qs.icc_anova(y, pd.Series(["a", "a", "b", "b", "c", "c"])) == 0.0
    assert qs.icc_anova(pd.Series([1.0, 1.0]), pd.Series(["a", "a"])) == 0.0
    assert qs.icc_anova(pd.Series([1, 1, 0, 0]), pd.Series(["a", "a", "b", "b"])) == pytest.approx(1.0)


def test_restrictions_and_exclusions() -> None:
    reports, links, lots = _simulate(n_lots=20, per_lot=10, seed=3)
    links.loc[links.index[:50], "match_level"] = "core"
    links.loc[links.index[50:60], "temporal_ok"] = False
    scales = attribute_scales(SPECS, lots, SCHEMA)
    f_all = qs.build_qc_safety_frame(reports, links, lots, scales, ["endotoxin"], drop_temporal_implausible=False)
    f_exact = qs.build_qc_safety_frame(reports, links, lots, scales, ["endotoxin"], restrict_levels=("exact",))
    f_noco = qs.build_qc_safety_frame(reports, links, lots, scales, ["endotoxin"], exclude_coadministered=True)
    assert len(f_all.data) == 200 and len(f_exact.data) == 140
    assert not f_noco.data["coadministered"].any() and "coadm" not in f_noco.covariate_terms
    lots["aloh3_conc"] = 4.0
    f_const = qs.build_qc_safety_frame(reports, links, lots, attribute_scales(SPECS, lots, SCHEMA), ["aloh3_conc"])
    assert any("no between-lot variation" in n for n in f_const.notes)
    assert qs.incremental_value(f_const, "ev_fever_39")["estimable"] is False
