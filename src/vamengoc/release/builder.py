"""Build the public, disclosure-controlled release from the pipeline results.

The release is the ONLY artefact that leaves the controlled environment. It
contains aggregated tables (CSV), a JSON bundle for the web application, LaTeX
macro files for the manuscripts, vector figures (EN/ES) and a manifest with
provenance and the disclosure-control log. ``vamengoc release verify`` checks
it before it may be committed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from vamengoc import __version__
from vamengoc.config import Project
from vamengoc.provenance import git_state
from vamengoc.release import figures as figs
from vamengoc.release.latex_tables import TableSet
from vamengoc.release.macros import MacroSet, join_words, lower_first
from vamengoc.release.sdc import (
    SECONDARY_TOKEN,
    SDCLog,
    suppress_column_secondary,
    suppress_counts,
    suppress_implied_pct,
    suppress_linked,
    suppress_long_secondary,
    suppress_wide_secondary,
)

if TYPE_CHECKING:
    from vamengoc.pipeline import PipelineOutputs
    from vamengoc.provenance import RunContext

__all__ = ["ATTRIBUTE_NAMES", "OUTCOME_NAMES", "build_release", "build_release_from_results"]

ATTRIBUTE_NAMES = {
    "en": {
        "ph": "pH",
        "protein_conc": "Protein concentration",
        "protein_adsorption": "Protein adsorption",
        "ps_conc": "Polysaccharide concentration",
        "ps_adsorption": "Polysaccharide adsorption",
        "aloh3_conc": "Al(OH)₃ concentration",
        "thiomersal_conc": "Thiomersal concentration",
        "bactericidal_titer": "Bactericidal titre (log₂)",
        "igg_elisa": "Anti-OMV IgG (log₁₀)",
        "endotoxin": "Endotoxin content (log₁₀)",
        "fill_volume": "Mean fill volume",
        "atypicality_t2": "Multivariate atypicality (T²)",
    },
    "es": {
        "ph": "pH",
        "protein_conc": "Concentración de proteínas",
        "protein_adsorption": "Adsorción de proteínas",
        "ps_conc": "Concentración de polisacárido",
        "ps_adsorption": "Adsorción de polisacárido",
        "aloh3_conc": "Concentración de Al(OH)₃",
        "thiomersal_conc": "Concentración de tiomersal",
        "bactericidal_titer": "Título bactericida (log₂)",
        "igg_elisa": "IgG anti-VME (log₁₀)",
        "endotoxin": "Contenido de endotoxinas (log₁₀)",
        "fill_volume": "Volumen medio del bulbo",
        "atypicality_t2": "Atipicidad multivariante (T²)",
    },
}
OUTCOME_NAMES = {
    "en": {
        "ev_fever_39": "Fever ≥39 °C",
        "ev_fever_40": "Fever ≥40 °C",
        "ev_severe_local_reaction": "Severe local reaction",
        "ev_persistent_crying": "Persistent crying",
        "ev_other": "Other event",
        "hospitalized": "Hospitalisation",
    },
    "es": {
        "ev_fever_39": "Fiebre ≥39 °C",
        "ev_fever_40": "Fiebre ≥40 °C",
        "ev_severe_local_reaction": "Reacción local severa",
        "ev_persistent_crying": "Llanto persistente",
        "ev_other": "Otro evento",
        "hospitalized": "Hospitalización",
    },
}
FEATURE_NAMES = {
    "en": {
        "age_months_log": "Age (log months)",
        "n_events": "Number of events",
        "female": "Female sex",
        "coadministered": "Co-administration",
        "age_missing": "Age missing",
    },
    "es": {
        "age_months_log": "Edad (log meses)",
        "n_events": "Número de eventos",
        "female": "Sexo femenino",
        "coadministered": "Coadministración",
        "age_missing": "Edad ausente",
    },
}


def _protect_nested_designs(dp: pd.DataFrame, min_cell: int, measures: list[str]) -> pd.DataFrame:
    """Withhold a design row whose counts differ from the primary design by a small count.

    Sensitivity designs are subsets of the primary design, so ``a_primary - a_design`` is itself a
    count of reports; when it is between 1 and ``min_cell - 1`` the design row is withheld.
    """
    out = dp.copy()
    prim = out[out["design"] == "primary_all_other_vaccines"].set_index("event")
    for c in ("a", *measures):
        if c in out:
            out[c] = out[c].astype(object)
    for i, r in out.iterrows():
        if r["design"] == "primary_all_other_vaccines" or r["event"] not in prim.index:
            continue
        for cnt in ("a", "b", "c", "d"):
            diff = _num(prim.loc[r["event"], cnt]) - _num(r[cnt])
            if 0 < diff < min_cell:
                if not 0 < _num(r["a"]) < min_cell:  # small a is suppressed as a primary cell later
                    out.loc[i, "a"] = SECONDARY_TOKEN
                for m in measures:
                    if m in out:
                        out.loc[i, m] = None
                break
    return out


def _protect_cumulative(cum: pd.DataFrame, min_cell: int, derived: list[str]) -> pd.DataFrame:
    """Withhold cumulative rows whose increment over the last released row is a small count."""
    out = cum.copy()
    out["a"] = out["a"].astype(object)
    for c in derived:
        out[c] = out[c].astype(object)
    for _, idx in out.groupby("event", sort=False).groups.items():
        last = 0.0
        for i in sorted(idx, key=lambda j: out.loc[j, "year"]):
            a = _num(out.loc[i, "a"])
            inc = a - last
            if 0 < inc < min_cell and a >= min_cell:
                out.loc[i, "a"] = SECONDARY_TOKEN
                for c in derived:
                    out.loc[i, c] = None
            else:
                last = a
    return out


def _protect_complement(df: pd.DataFrame, total: str, part: str, min_cell: int) -> pd.DataFrame:
    """Withhold ``part`` when ``total - part`` is a small count."""
    out = df.copy()
    diff = pd.to_numeric(out[total], errors="coerce") - pd.to_numeric(out[part], errors="coerce")
    risky = (diff > 0) & (diff < min_cell) & (pd.to_numeric(out[part], errors="coerce") >= min_cell)
    if risky.any():
        out[part] = out[part].astype(object)
        out.loc[risky, part] = SECONDARY_TOKEN
    return out


def _protect_subset_events(sens: pd.DataFrame, primary: pd.DataFrame, min_cell: int) -> pd.DataFrame:
    """Withhold event counts of sensitivity subsets that differ from the primary by a small count."""
    if not len(sens) or "n_events" not in sens:
        return sens
    out = sens.copy()
    ref = primary[primary["model"] == "single"].drop_duplicates("outcome").set_index("outcome")["n_events"]
    out["n_events"] = out["n_events"].astype(object)
    for i, r in out.iterrows():
        if r["outcome"] in ref.index:
            diff = _num(ref.loc[r["outcome"]]) - _num(r["n_events"])
            if 0 < diff < min_cell and _num(r["n_events"]) >= min_cell:
                out.loc[i, "n_events"] = SECONDARY_TOKEN
    return out


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating | float):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.DataFrame):
        return _jsonable(o.to_dict(orient="records"))
    if isinstance(o, pd.Timestamp | dt.date):
        return o.isoformat()
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Writer:
    def __init__(self, root: Path, project: Project) -> None:
        self.root = root
        self.cfg = project.config.sdc
        self.log = SDCLog()
        self.schema: dict[str, dict[str, Any]] = {}
        self.tables: dict[str, pd.DataFrame] = {}
        self.jsons: dict[str, Any] = {}

    def table(
        self,
        name: str,
        df: pd.DataFrame,
        *,
        person_counts: list[str] | None = None,
        derived: dict[str, list[str]] | None = None,
        linked: dict[str, list[str]] | None = None,
        description: str = "",
        secondary: dict[str, Any] | None = None,
        implied: tuple[str, list[str]] | None = None,
        column_secondary: dict[str, Any] | None = None,
        implied_scale: float = 100.0,
    ) -> pd.DataFrame:
        """Write one released table after disclosure control.

        ``secondary`` (keys ``block_cols``, ``row_col``, ``group_col``, ``count_col``,
        ``derived``) adds complementary suppression; ``implied`` = (denominator column,
        percentage columns) blanks percentages that imply a small count.
        """
        pc = [c for c in (person_counts or []) if c in df.columns]
        out = df.copy()
        for trig, cols in (linked or {}).items():
            if trig in out:
                out = suppress_linked(out, trig, cols, min_cell=self.cfg.min_cell, table=name, log=self.log)
        out = suppress_counts(
            out,
            pc,
            min_cell=self.cfg.min_cell,
            token=self.cfg.suppression_token,
            derived=derived,
            table=name,
            log=self.log,
        )
        if secondary is not None and self.cfg.secondary_suppression:
            out = suppress_long_secondary(
                out,
                min_cell=self.cfg.min_cell,
                token=self.cfg.suppression_token,
                table=name,
                log=self.log,
                **secondary,
            )
        if column_secondary is not None and self.cfg.secondary_suppression:
            out = suppress_column_secondary(
                out, token=self.cfg.suppression_token, table=name, log=self.log, **column_secondary
            )
        if implied is not None:
            out = suppress_implied_pct(
                out,
                implied[0],
                implied[1],
                min_cell=self.cfg.min_cell,
                table=name,
                log=self.log,
                scale=implied_scale,
            )
        for c in out.columns:
            if out[c].dtype.kind == "f":
                out[c] = out[c].round(6)
        path = self.root / "tables" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
        self.schema[name] = {"person_count_columns": pc, "description": description, "rows": len(out)}
        self.tables[name] = out
        return out

    def json(self, name: str, obj: Any) -> None:
        path = self.root / "tables" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _jsonable(obj)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        self.jsons[name] = payload

    def small(self, v: Any) -> Any:
        """SDC for a scalar person count placed in JSON or macros."""
        try:
            x = float(v)
        except (TypeError, ValueError):
            return v
        return self.cfg.suppression_token if 0 < x < self.cfg.min_cell else v


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def _paper1_tables(w: _Writer, p1: dict[str, Any], labels: dict[str, Any], target: str) -> None:
    # "All" (= target + other) is not released: it would let a suppressed cell be recovered by
    # subtraction; tables recompute it only when both groups are visible. age_group is a coarsening
    # of age_band and is dropped for the same reason.
    chars = p1["characteristics"]
    chars = chars[(chars["group"] != "All") & (chars["variable"] != "age_group")].reset_index(drop=True)
    w.table(
        "p1_characteristics",
        chars,
        person_counts=["n", "denominator"],
        derived={"n": ["pct"]},
        description="Characteristics of AEFI reports, target vs other vaccines",
        secondary={
            "block_cols": ["variable"],
            "row_col": "level",
            "group_col": "group",
            "count_col": "n",
            "derived": ["pct"],
        },
    )
    cont = p1["characteristics_continuous"]
    w.table(
        "p1_characteristics_continuous",
        cont,
        person_counts=["n"],
        derived={"n": ["median", "q1", "q3"]},
        description="Age and notification delay: median and IQR",
    )
    ef = p1["event_frequency"]
    w.table(
        "p1_event_frequency",
        ef[ef["group"] != "All"].reset_index(drop=True),
        person_counts=["n", "denominator"],
        derived={"n": ["pct"]},
        description="Event indicators among reports (target and other vaccines)",
    )
    w.table(
        "p1_reports_by_year",
        p1["reports_by_year"],
        person_counts=["n_reports", "n_target", "n_target_only", "n_hospitalized", "n_target_hospitalized"],
        description="Annual report counts (analytic year)",
        column_secondary={
            "cols": ["n_reports", "n_target", "n_target_only", "n_hospitalized", "n_target_hospitalized"]
        },
    )
    rate_derived = {"count": ["rate_per_100k", "rate_lo", "rate_hi", "ratio_to_expected"]}
    w.table(
        "p1_rates_target",
        p1["rates_all_target"],
        person_counts=["count"],
        derived=rate_derived,
        description="VA-MENGOC-BC reporting rate per 100 000 doses",
        column_secondary={"cols": ["count"], "derived": rate_derived},
    )
    if len(p1["rates_by_event"]):
        w.table(
            "p1_rates_by_event",
            p1["rates_by_event"],
            person_counts=["count"],
            derived=rate_derived,
            description="Event-specific reporting rates per 100 000 doses",
            column_secondary={"cols": ["count"], "block_col": "event", "derived": rate_derived},
        )
    w.table(
        "p1_rates_hospitalized",
        p1["rates_hospitalized"],
        person_counts=["count"],
        derived=rate_derived,
        description="Reporting rate of hospitalised AEFI per 100 000 doses",
        column_secondary={"cols": ["count"], "derived": rate_derived},
    )
    w.json("p1_rates_trend", p1["rates_trend"])
    measures = [
        "expected",
        "ror",
        "ror_lo",
        "ror_hi",
        "prr",
        "prr_lo",
        "prr_hi",
        "chi2_yates",
        "ic",
        "ic025",
        "ic975",
        "fisher_p",
        "fisher_p_bh",
        "ebgm",
        "eb05",
        "eb95",
    ]
    dp = _protect_nested_designs(p1["disproportionality"].copy(), w.cfg.min_cell, measures)
    # Design sizes are released separately; b, c and d are not released (with the totals they
    # would reveal a suppressed a by subtraction).
    sizes = (
        dp.assign(
            n_target=pd.to_numeric(dp["a"], errors="coerce") + pd.to_numeric(dp["b"], errors="coerce"),
            n_comparator=pd.to_numeric(dp["c"], errors="coerce") + pd.to_numeric(dp["d"], errors="coerce"),
        )
        .groupby("design", sort=False)[["n_target", "n_comparator"]]
        .max()
        .reset_index()
    )
    w.table(
        "p1_design_sizes",
        sizes,
        person_counts=["n_target", "n_comparator"],
        description="Reports in the target and comparator groups of each disproportionality design",
    )
    dp = dp.drop(columns=["b", "c", "d"])
    dp["label_en"] = dp["event"].map(lambda e: labels.get(e, {}).get("label_en", e))
    dp["label_es"] = dp["event"].map(lambda e: labels.get(e, {}).get("label_es", e))
    w.table(
        "p1_disproportionality",
        dp,
        person_counts=["a"],
        linked={"a": measures},
        description="Disproportionality by design (READUS-PV); b, c, d withheld (see p1_design_sizes)",
    )
    w.json("p1_mgps_prior", p1["mgps_prior"])
    if len(p1["cumulative_ic"]):
        w.table(
            "p1_cumulative_ic",
            _protect_cumulative(p1["cumulative_ic"], w.cfg.min_cell, ["expected", "ic", "ic025", "ic975"]),
            person_counts=["a"],
            linked={"a": ["expected", "ic", "ic025", "ic975"]},
            description="Cumulative IC by year",
        )
    sel = p1["lca_selection"].copy()
    sel["n_reports"] = int(pd.to_numeric(p1["reports_by_year"]["n_reports"]).sum())
    w.table(
        "p1_lca_selection",
        sel,
        description="LCA model selection",
        implied=("n_reports", ["smallest_class_pct"]),
    )
    byg = p1["lca_by_group"]
    wide = byg.pivot(index="lca_class", columns="group", values="n").fillna(0).reset_index()
    groups = [c for c in wide.columns if c != "lca_class"]
    wide_s = suppress_wide_secondary(
        wide, groups, min_cell=w.cfg.min_cell, token=w.cfg.suppression_token, table="p1_lca_by_group", log=w.log
    )
    long_s = wide_s.melt(id_vars="lca_class", var_name="group", value_name="n")
    w.table("p1_lca_by_group", long_s, description="Latent class membership by vaccine group (secondary SDC)")
    w.schema["p1_lca_by_group"]["person_count_columns"] = ["n"]
    class_n = byg.groupby("lca_class")["n"].sum()
    prof = p1["lca_profiles"].copy()
    small_classes = set(class_n[class_n < w.cfg.min_cell].index)
    prof.loc[prof["class"].isin(small_classes), "probability"] = None
    prof["label_en"] = prof["item"].map(lambda e: labels.get(e, {}).get("label_en", e))
    prof["label_es"] = prof["item"].map(lambda e: labels.get(e, {}).get("label_es", e))
    w.table("p1_lca_profiles", prof, description="Item-response probabilities of the selected LCA model")
    w.json(
        "p1_lca_summary",
        {
            "best_k": p1["lca_best_k"],
            "bootstrap_ari_median": p1["lca_bootstrap_ari_median"],
            "group_test": p1.get("lca_group_test"),
        },
    )
    w.table(
        "p1_cooccurrence_target",
        p1["cooccurrence_target"],
        person_counts=["n_both"],
        linked={"n_both": ["log_or", "lo", "hi"]},
        description="Pairwise co-reporting (log OR)",
    )
    ser = p1["seriousness"]
    w.table(
        "p1_seriousness_logistic",
        ser.logistic,
        person_counts=["n_with_term"],
        linked={"n_with_term": ["or", "or_lo", "or_hi", "p_value"]},
        description="Adjusted odds ratios of hospitalisation (Firth logistic regression)",
    )
    w.json(
        "p1_seriousness_metrics",
        {
            "n_train": w.small(ser.n_train),
            "n_test": w.small(ser.n_test),
            "events_train": w.small(ser.events_train),
            "events_test": w.small(ser.events_test),
            "metrics": ser.metrics,
            "notes": ser.notes,
        },
    )
    w.table("p1_shap_importance", ser.shap_importance, description="Mean |SHAP| (temporal test set)")
    if len(ser.shap_dependence):
        w.table(
            "p1_shap_dependence",
            ser.shap_dependence,
            person_counts=["n"],
            derived={"n": ["mean_shap"]},
            description="Binned SHAP dependence",
        )
    if len(ser.calibration):
        w.table(
            "p1_calibration",
            ser.calibration,
            person_counts=["n"],
            derived={"n": ["observed", "predicted"]},
            description="Calibration by decile (temporal test set)",
            implied=("n", ["observed"]),
            implied_scale=1.0,
        )
    nd = p1["notification_delay_by_year"].drop(columns=["min", "max"], errors="ignore")
    w.table(
        "p1_notification_delay",
        nd,
        person_counts=["count"],
        derived={"count": ["mean", "std", "25%", "50%", "75%", "90%"]},
        description="Notification delay (days) by year",
    )
    for name, key, desc in (
        ("p1_monthly_all", "monthly_all", "Monthly reports, all"),
        ("p1_monthly_target", "monthly_target", "Monthly reports, VA-MENGOC-BC"),
    ):
        monthly = p1[key].copy()
        monthly["year"] = monthly["month"].astype(str).str[:4]
        w.table(
            name,
            monthly,
            person_counts=["count"],
            description=desc,
            column_secondary={"cols": ["count"], "block_col": "year"},
        )
    w.json(
        "p1_monthly_changepoints", {"all": p1["monthly_changepoints_all"], "target": p1["monthly_changepoints_target"]}
    )
    its = dict(p1["incidence_its"])
    fitted = its.pop("fitted")
    w.json("context_incidence_its", its)
    w.table("context_incidence_fitted", fitted, description="Annual cases and segmented NB fit (public series)")
    w.table("context_incidence", p1["incidence"], description="National meningococcal disease series (public)")
    w.table("context_coverage", p1["coverage"], description="VA-MENGOC-BC doses and coverage (public)")
    _ = target


def _paper2_tables(w: _Writer, p2: dict[str, Any], project: Project, lot_values: str) -> dict[str, Any]:
    scales = p2["scales"]
    if project.config.sdc.release_specifications:
        w.json("p2_specifications", {k: v["spec"] for k, v in scales.items()})
        w.json("p2_scales", {k: {kk: vv for kk, vv in v.items() if kk != "spec"} for k, v in scales.items()})
    else:
        # Only the kind of limit and the analysis transform: absolute limits and units stay local.
        w.json("p2_specifications", {k: {"op": v["spec"].get("op")} for k, v in scales.items()})
        w.json("p2_scales", {k: {"transform": v["transform"], "one_sided": v["one_sided"]} for k, v in scales.items()})
    cap = p2["capability"].copy()
    if lot_values != "raw":
        cap = cap.drop(columns=["mean", "sd"], errors="ignore")
    w.table("p2_capability", cap, description="Process capability (Ppk) by period")
    ch = p2["control_charts"]
    q = ch.groupby(["attribute", "production_year"])["window_position"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).unstack()
    q.columns = ["q10", "q25", "q50", "q75", "q90"]
    q["n_lots"] = ch.groupby(["attribute", "production_year"]).size()
    q = q.reset_index()
    q.loc[q["n_lots"] < w.cfg.min_cell, ["q10", "q25", "q50", "q75", "q90"]] = None
    w.table("p2_qc_annual_quantiles", q, description="Annual quantiles of the window position (lot level)")
    if lot_values in ("normalized", "raw"):
        cols = [
            "attribute",
            "seq",
            "production_year",
            "window_position",
            "z",
            "ewma",
            "ewma_ucl",
            "ewma_lcl",
            "rule1",
            "rule2",
            "rule3",
            "rule5",
            "ewma_signal",
        ]
        series = ch[cols].copy()
        if lot_values == "normalized":
            series = series.drop(columns=["ewma", "ewma_ucl", "ewma_lcl"])
            series["ewma_window"] = np.nan
            for a, s in scales.items():
                m = series["attribute"] == a
                width = s["window_high"] - s["window_low"]
                series.loc[m, "ewma_window"] = (ch.loc[m, "ewma"] - s["window_low"]) / width
                series.loc[m, "ewma_ucl_window"] = (ch.loc[m, "ewma_ucl"] - s["window_low"]) / width
                series.loc[m, "ewma_lcl_window"] = (ch.loc[m, "ewma_lcl"] - s["window_low"]) / width
        w.table(
            "p2_lot_series",
            series,
            description="Per-lot series on the specification-window scale (pseudonymous sequence number)",
        )
    w.table("p2_control_chart_summary", p2["control_chart_summary"], description="Run-rule signals per attribute")
    cps = p2["changepoints"].copy()
    if lot_values != "raw" and len(cps):
        for c in ("mean_before", "mean_after"):
            cps[c + "_window"] = [
                (_num(r[c]) - scales[r["attribute"]]["window_low"])
                / (scales[r["attribute"]]["window_high"] - scales[r["attribute"]]["window_low"])
                for _, r in cps.iterrows()
            ]
        cps = cps.drop(columns=["mean_before", "mean_after"])
    w.table("p2_changepoints", cps, description="PELT change points in the production sequence")
    ms = p2["mspc_scores"]
    tq = ms.groupby("production_year")["t2"].quantile([0.25, 0.5, 0.75, 0.9]).unstack()
    tq.columns = ["q25", "q50", "q75", "q90"]
    tq["n_lots"] = ms.groupby("production_year").size()
    tq["n_t2_flagged"] = ms.groupby("production_year")["t2_flag"].sum()
    tq["n_spe_flagged"] = ms.groupby("production_year")["spe_flag"].sum()
    w.table("p2_mspc_t2_quantiles", tq.reset_index(), description="Hotelling T2 by production year")
    w.json("p2_mspc_summary", p2["mspc_summary"])
    w.table("p2_mspc_loadings", p2["mspc_loadings"], description="PCA loadings (robust correlation)")
    w.table("p2_attribute_correlation", p2["attribute_correlation"], description="Spearman correlation")
    w.table("p2_equivalence", p2["equivalence"], description="National vs export lots: TOST and HL shift")
    w.json("p2_energy_test", p2["energy_test"])
    ls = dict(p2["linkage_summary"])
    ls_safe = {
        "n_target_reports": w.small(ls["n_target_reports"]),
        "n_linked": w.small(ls["n_linked"]),
        "link_rate": ls["link_rate"],
        "by_level": {k: w.small(v) for k, v in ls["by_level"].items()},
        "n_distinct_lots_linked": ls["n_distinct_lots_linked"],
        "temporal_implausible": w.small(ls["temporal_implausible"]),
    }
    w.json("p2_linkage_summary", ls_safe)
    by_year = pd.DataFrame(ls["by_year"])
    if len(by_year):
        w.table(
            "p2_linkage_by_year",
            _protect_complement(by_year, "n_reports", "n_linked", w.cfg.min_cell),
            person_counts=["n_reports", "n_linked"],
            description="Linkage by analytic year",
        )
    w.table(
        "p2_linkage_bias",
        p2["linkage_bias"],
        person_counts=["n"],
        derived={"n": ["age_months_median", "female_pct", "fever39_pct", "hospitalized_pct", "coadministered_pct"]},
        description="Linked vs unlinked reports",
        implied=("n", ["female_pct", "fever39_pct", "hospitalized_pct", "coadministered_pct"]),
    )
    fs = dict(p2["qc_frame_summary"])
    sd = fs.pop("exposure_sd")
    if lot_values != "raw":
        fs["exposure_sd_window"] = {
            k: v / (scales[k]["window_high"] - scales[k]["window_low"]) for k, v in sd.items() if k in scales
        }
    else:
        fs["exposure_sd"] = sd
    fs["n_reports"] = w.small(fs["n_reports"])
    rpl = fs.pop("reports_per_lot")
    fs["reports_per_lot"] = {k: rpl[k] for k in ("mean", "50%", "25%", "75%") if k in rpl}
    w.json("p2_qc_frame_summary", fs)
    gee_counts = ["n", "n_events"]
    w.table(
        "p2_gee_primary",
        p2["gee"],
        person_counts=gee_counts,
        linked={"n_events": ["or_per_sd", "or_lo", "or_hi", "p_value", "p_bh"]},
        description="Prespecified GEE family (exchangeable)",
    )
    w.table(
        "p2_gee_exploratory",
        p2["gee_exploratory"],
        person_counts=gee_counts,
        linked={"n_events": ["or_per_sd", "or_lo", "or_hi", "p_value", "p_bh"]},
        description="Exploratory GEE family (independence, cluster-robust)",
    )
    if len(p2["gee_sensitivity"]):
        w.table(
            "p2_gee_sensitivity",
            _protect_subset_events(p2["gee_sensitivity"], p2["gee"], w.cfg.min_cell),
            person_counts=gee_counts,
            linked={"n_events": ["or_per_sd", "or_lo", "or_hi", "p_value", "p_bh"]},
            description="Sensitivity analyses",
        )
    w.table("p2_mixed_model", p2["mixed_model"], description="Bayesian random-intercept model (VB)")
    w.table("p2_lot_level", p2["lot_level"], description="Lot-level quasi-binomial models")
    w.table("p2_mde", p2["mde"], description="Minimum detectable OR per SD (80% power)")
    w.table(
        "p2_incremental_value",
        p2["incremental_value"],
        person_counts=["n_reports"],
        description="Incremental information of QC attributes (lot-grouped CV)",
    )
    return {"quantiles": q, "t2_quantiles": tq.reset_index()}


def _dq_tables(w: _Writer, dq: dict[str, Any]) -> None:
    w.table(
        "dq_plausibility",
        dq["plausibility"],
        person_counts=["n_records", "n_flagged"],
        derived={"n_flagged": ["pct_flagged"]},
        description="Plausibility checks by source-file year",
    )
    conf = dq["conformance"]
    w.table(
        "dq_conformance",
        conf,
        person_counts=[c for c in conf.columns if c.startswith("n")],
        description="Parse outcomes by file and field",
    )
    w.table(
        "dq_completeness",
        dq["completeness"],
        person_counts=["n", "n_present"],
        derived={"n_present": ["pct_present"]},
        description="Completeness by file year",
    )
    norm = {
        k: {
            "n_values": v["n_values"],
            "n_distinct_inputs": v["n_distinct_inputs"],
            "by_rule": {r: w.small(n) for r, n in v["by_rule"].items()},
        }
        for k, v in dq["normalisation"].items()
    }
    dedup = {
        k: (w.small(v) if isinstance(v, int | np.integer) else v)
        for k, v in dq["dedup"].items()
        if k != "exact_duplicates_by_file"
    }
    dedup["exact_duplicates_by_file"] = {k: w.small(v) for k, v in dq["dedup"]["exact_duplicates_by_file"].items()}
    lots = dict(dq["lots_sheet"])
    lots.pop("spec_text", None)
    w.json(
        "dq_summary",
        {
            "schema_drift": dq["schema_drift"],
            "dedup": dedup,
            "window": dq["window"],
            "normalisation": norm,
            "lots_sheet": lots,
            "files": {
                f: {
                    k: r[k]
                    for k in (
                        "sheet",
                        "header_row",
                        "n_columns",
                        "n_matched",
                        "missing_required",
                        "missing_optional",
                        "n_data_rows",
                        "file_year",
                    )
                    if k in r
                }
                | {
                    "junk_columns": [
                        {"column": j["column"], "n_nonnull": w.small(j["n_nonnull"])} for j in r.get("junk_columns", [])
                    ],
                    "fuzzy_matches": r.get("fuzzy_matches", []),
                    "unmatched_columns": r.get("unmatched_columns", []),
                }
                for f, r in dq["schema_reports"].items()
            },
            "series": dq["series_reports"],
        },
    )
    w.json("provenance_notes", dq["provenance_notes"])


def _macros(w: _Writer, results: dict[str, Any], project: Project, root: Path, synthetic: bool) -> list[Path]:
    a = project.config.analysis
    token = w.cfg.suppression_token
    common = MacroSet("V", suppression_token=token)
    common.text("DataOrigin", "synthetic" if synthetic else "real")
    common.text("StudyFirstYear", str(a.study_years[0]))
    common.text("StudyLastYear", str(a.study_years[1]))
    common.number("MinCell", w.cfg.min_cell)
    common.text("Seed", str(a.seed))
    common.text("CodeVersion", __version__)
    dq = results["data_quality"]
    common.number("ReportsRaw", w.small(dq["dedup"]["rows_in"]))
    common.number("ExactDuplicates", w.small(dq["dedup"]["exact_duplicates_removed"]))
    common.number("KeyDuplicatesMerged", w.small(dq["dedup"]["key_duplicate_rows_merged"]))
    common.number("ReportsDedup", w.small(dq["dedup"]["rows_out"]))
    common.number("ReportsInWindow", w.small(dq["window"]["n_in_window"]))
    common.number("ReportsOutsideWindow", w.small(dq["window"]["n_outside_window"]))
    common.number("NFiles", len(dq["schema_reports"]))
    rel = project.config.release
    for name, value, what in (
        ("ExtractionDate", rel.data_extraction_date, ("date of data extraction", "fecha de extracción de los datos")),
        ("Custodian", rel.database_custodian, ("database custodian", "custodio de la base de datos")),
    ):
        if value:
            common.text(name, str(value))
        else:
            common.bilingual(name, f"[authors to complete: {what[0]}]", f"[a completar por los autores: {what[1]}]")
    paths = [common.write(root / "latex" / "macros_common.tex", "Common macros")]

    p1 = results["paper1"]
    m1 = MacroSet("PO", suppression_token=token)  # "PO" = paper one
    rby = w.tables["p1_reports_by_year"]
    m1.number("NReports", w.small(int(pd.to_numeric(p1["reports_by_year"]["n_reports"]).sum())))
    m1.number("NTarget", w.small(int(pd.to_numeric(p1["reports_by_year"]["n_target"]).sum())))
    m1.number("NTargetOnly", w.small(int(pd.to_numeric(p1["reports_by_year"]["n_target_only"]).sum())))
    m1.number(
        "NOther",
        w.small(
            int(pd.to_numeric(p1["reports_by_year"]["n_reports"]).sum())
            - int(pd.to_numeric(p1["reports_by_year"]["n_target"]).sum())
        ),
    )
    m1.number("NTargetHosp", w.small(int(pd.to_numeric(p1["reports_by_year"]["n_target_hospitalized"]).sum())))
    tot = pd.to_numeric(p1["reports_by_year"]["n_reports"]).sum()
    m1.percent("PctTarget", 100 * pd.to_numeric(p1["reports_by_year"]["n_target"]).sum() / tot if tot else None)
    _ = rby
    tr = p1["rates_trend"]
    if tr.get("estimable"):
        m1.number("PooledRate", tr["pooled_rate_per_100k"], 1)
        m1.interval("PooledRateCI", tr["pooled_rate_lo"], tr["pooled_rate_hi"], 1)
        m1.number("TrendRR", tr["rr_per_year"], 3)
        m1.interval("TrendRRCI", tr["rr_lo"], tr["rr_hi"], 3)
        m1.pvalue("TrendP", tr["p_value"])
        m1.number("Dispersion", tr["dispersion"], 2)
        m1.text("RateFirstYear", str(int(tr["first_year"])))
        m1.text("RateLastYear", str(int(tr["last_year"])))
    m1.number("ExpectedRate", a.expected_national_rate_per_100k)
    dp = w.tables["p1_disproportionality"]
    prim = dp[dp["design"] == "primary_all_other_vaccines"].set_index("event")
    for ev in (
        "ev_fever_39",
        "ev_fever_40",
        "ev_severe_local_reaction",
        "ev_persistent_crying",
        "ev_febrile_seizure",
        "ev_collapse",
        "ev_allergic_reaction",
        "ev_rash",
        "ev_other",
    ):
        if ev not in prim.index:
            continue
        r = prim.loc[ev]
        m1.number(f"{ev} A", r["a"])
        m1.number(f"{ev} ROR", r["ror"], 2)
        m1.interval(
            f"{ev} RORCI",
            _num(r["ror_lo"]) if r["ror_lo"] is not None else None,
            _num(r["ror_hi"]) if r["ror_hi"] is not None else None,
            2,
        )
        m1.number(f"{ev} ICLow", r["ic025"], 2)
        m1.number(f"{ev} EBLow", r.get("eb05"), 2)
    sig_col = "signal_primary" if "signal_primary" in dp.columns else "signal_any"
    n_signals = {d: int(g[sig_col].astype(bool).sum()) for d, g in dp.groupby("design")}
    for d, n in n_signals.items():
        m1.number(f"Signals {d}", n)
    for d, g in dp.groupby("design"):
        m1.number(f"SignalsAny {d}", int(g["signal_any"].astype(bool).sum()))
    m1.number("NEventsScreened", int(prim.shape[0]))
    # Analysis settings quoted in the Methods (from the versioned configuration).
    sm_cfg, lc = a.seriousness_model, a.lca
    m1.text("TrainYears", f"{sm_cfg.train_years[0]}--{sm_cfg.train_years[1]}")
    m1.text("TestYears", f"{sm_cfg.test_years[0]}--{sm_cfg.test_years[1]}")
    m1.number("LCAKMin", lc.k_range[0])
    m1.number("LCAKMax", lc.k_range[1])
    m1.number("LCAStarts", lc.n_starts)
    m1.number("LCABootstrap", lc.bootstrap)
    m1.number("InfantMonths", a.infant_comparator_max_age_months + 1)
    m1.number("DispMinReports", a.disproportionality.min_reports)
    fitted = p1["incidence_its"].get("fitted")
    if fitted is not None and len(fitted):
        m1.text("ITSFirstYear", str(int(fitted["year"].min())))
        m1.text("ITSLastYear", str(int(fitted["year"].max())))
    its_cfg = p1["incidence_its"]
    m1.text("ITSTransition", f"{its_cfg['intervention_year']}--{its_cfg['end_transition']}")
    m1.number("NVaccines", p1.get("n_vaccines"))
    _p1_words(m1, dp, sig_col, p1, project, a.expected_national_rate_per_100k)
    m1.number("LCABestK", p1["lca_best_k"])
    m1.number("LCAAri", p1["lca_bootstrap_ari_median"], 2)
    gt = p1.get("lca_group_test") or {}
    m1.number("LCAChi", gt.get("chi2"), 1)
    m1.number("LCADf", gt.get("dof"))
    m1.pvalue("LCAP", gt.get("p_value"))
    sres = p1["seriousness"]
    m1.number("NTrain", w.small(sres.n_train))
    m1.number("NTest", w.small(sres.n_test))
    m1.number("EventsTrain", w.small(sres.events_train))
    m1.number("EventsTest", w.small(sres.events_test))
    ser = sres.metrics
    for k, v in ser.items():
        for mk in ("auroc", "auprc", "brier", "cal_intercept", "cal_slope"):
            m1.number(f"{k} {mk}", v.get(mk), 3)
    its = p1["incidence_its"]
    m1.number("ITSLevelRR", its["level_change_rr"]["rr"], 3)
    m1.interval("ITSLevelRRCI", its["level_change_rr"]["lo"], its["level_change_rr"]["hi"], 3)
    m1.number("ITSPreRR", its["pre_trend_rr_per_year"]["rr"], 3)
    m1.number("ITSPostRR", its["post_trend_rr_per_year"]["rr"], 3)
    m1.number("ITSRatePre", its["mean_rate_pre"], 1)
    m1.number("ITSRatePost", its["mean_rate_post"], 2)
    cp = p1["monthly_changepoints_all"]
    m1.number("NBreaksAll", len(cp.get("breaks", [])))
    m1.counted(
        "NBreaksAllPhrase",
        len(cp.get("breaks", [])),
        ("change point", "change points"),
        ("punto de cambio", "puntos de cambio"),
    )
    m1.text("BreaksAll", ", ".join(cp.get("breaks", [])) or "none")
    nd = p1["notification_delay_by_year"]
    m1.number("DelayMedian", float(pd.to_numeric(nd["50%"]).median()) if len(nd) else None, 1)
    paths.append(m1.write(root / "latex" / "macros_p1.tex", "Paper 1 macros"))

    p2 = results["paper2"]
    m2 = MacroSet("PT", suppression_token=token)  # "PT" = paper two
    m2.number("NLots", int(p2["mspc_summary"]["n_lots"]))
    m2.number("NNationalLots", int(p2["mspc_scores"]["national"].sum()))
    m2.number("NExportLots", int(p2["mspc_summary"]["n_lots"]) - int(p2["mspc_scores"]["national"].sum()))
    py = pd.to_numeric(p2["mspc_scores"]["production_year"], errors="coerce").dropna()
    if len(py):
        m2.text("LotFirstYear", str(int(py.min())))
        m2.text("LotLastYear", str(int(py.max())))
    cap_periods = [p for p in dict.fromkeys(p2["capability"]["period"].astype(str)) if p != "all"]
    for i, per in enumerate(cap_periods[:2]):
        m2.text(f"Period {('One', 'Two')[i]}", per.replace("-", "--"))
    qcfg, scfg, lcfg = a.qc, a.qc_safety, a.linkage
    m2.percent("EqMarginPct", 100 * qcfg.equivalence_margin_fraction, 0)
    m2.number("EWMALambda", qcfg.ewma_lambda, 1)
    m2.number("MSPCAlpha", qcfg.mspc_alpha, 2)
    m2.number("CapBootstrap", qcfg.capability_bootstrap)
    m2.number("CVFolds", scfg.cv_folds)
    m2.number("FuzzyThreshold", lcfg.fuzzy_threshold)
    m2.number("MaxYearsAfterProduction", lcfg.max_years_after_production)
    m2.number("NAttributes", len(p2["scales"]))
    m2.number("NComponents", p2["mspc_summary"]["n_components"])
    ev = p2["mspc_summary"]["explained_variance"]
    m2.percent("ExplainedVar", 100 * float(np.sum(ev[: p2["mspc_summary"]["n_components"]])))
    m2.number("TTwoFlagged", p2["mspc_summary"]["t2_flagged"])
    m2.number("SPEFlagged", p2["mspc_summary"]["spe_flagged"])
    cap = p2["capability"]
    capall = cap[cap["period"] == "all"]
    m2.number("NAttrPpkAbove", int((pd.to_numeric(capall["ppk"]) >= 1.33).sum()))
    m2.number("NAttrPpkBelowOne", int((pd.to_numeric(capall["ppk"]) < 1.0).sum()))
    m2.percent("PctConforming", float(pd.to_numeric(capall["pct_conforming"]).min()), 1)
    m2.number("NChangepoints", len(p2["changepoints"]))
    eq = p2["equivalence"]
    m2.number("NEquivalent", int(eq["equivalent"].astype(bool).sum()))
    m2.pvalue("EnergyP", p2["energy_test"]["p_value"])
    ls = p2["linkage_summary"]
    m2.number("NTargetReports", w.small(ls["n_target_reports"]))
    m2.number("NLinked", w.small(ls["n_linked"]))
    m2.percent("LinkRate", 100 * ls["link_rate"] if ls["link_rate"] is not None else None)
    m2.number("NLinkedLots", ls["n_distinct_lots_linked"])
    for lvl in ("exact", "core", "fuzzy", "no_lot_recorded", "no_match"):
        m2.number(f"Link {lvl}", w.small(ls["by_level"].get(lvl, 0)))
    m2.number("TemporalImplausible", w.small(ls.get("temporal_implausible", 0)))
    fs = p2["qc_frame_summary"]
    m2.number("NAnalysed", w.small(fs["n_reports"]))
    m2.number(
        "ExcludedOther",
        w.small(max(int(ls["n_linked"]) - int(ls.get("temporal_implausible", 0)) - int(fs["n_reports"]), 0)),
    )
    m2.number("NAnalysedLots", fs["n_lots"])
    m2.number("ReportsPerLot", fs["reports_per_lot"].get("50%"), 1)
    g = w.tables["p2_gee_primary"]
    single = g[g["model"] == "single"]
    for _, r in single.iterrows():
        key = f"{r['outcome']} {r['exposure']}"
        m2.number(f"{key} OR", r["or_per_sd"], 2)
        m2.interval(
            f"{key} CI",
            _num(r["or_lo"]) if r["or_lo"] is not None else None,
            _num(r["or_hi"]) if r["or_hi"] is not None else None,
            2,
        )
        m2.pvalue(f"{key} P", r["p_value"])
        m2.pvalue(f"{key} Q", r.get("p_bh"))
    m2.number("NSignificantFDR", int((pd.to_numeric(single["p_bh"], errors="coerce") < a.qc_safety.fdr_alpha).sum()))
    for _, r in p2["mde"].iterrows():
        m2.number(f"{r['outcome']} MDE", r["mde_or_per_sd"], 2)
        m2.number(f"{r['outcome']} ICC", r["icc"], 3)
        m2.percent(f"{r['outcome']} Prev", 100 * r["outcome_prevalence"], 1)
    for _, r in p2["incremental_value"].iterrows():
        if r.get("estimable"):
            m2.number(f"{r['outcome']} DeltaAUC", r["delta_auc"], 3)
            m2.pvalue(f"{r['outcome']} PermP", r["perm_p"])
            m2.number(f"{r['outcome']} AUCBase", r["auc_base"], 3)
    m2.number("NPermutations", project.config.analysis.qc_safety.permutation_tests)
    _p2_words(m2, g, p2, a.qc_safety.fdr_alpha)
    paths.append(m2.write(root / "latex" / "macros_p2.tex", "Paper 2 macros"))
    return paths


def _term_label(labels: dict[str, Any], vaccines: dict[str, Any] | None = None) -> Any:
    """Bilingual display name of a model term (features, vaccines, regions, events)."""
    vac = vaccines or {}

    def short(code: str, lang: str) -> str:
        full = str(vac.get(code, {}).get(f"label_{lang}", code))
        return full.split(" (", maxsplit=1)[0]

    def f(term: str) -> tuple[str, str]:
        if term in FEATURE_NAMES["en"]:
            return FEATURE_NAMES["en"][term], FEATURE_NAMES["es"][term]
        if term.startswith("vac_"):
            v = term.removeprefix("vac_")
            return f"Vaccine: {short(v, 'en')}", f"Vacuna: {short(v, 'es')}"
        if term.startswith("region_"):
            r = term.removeprefix("region_")
            en = {"Centro": "Central", "Oriente": "Eastern"}.get(r, r)
            return f"{en} region (vs western)", f"Región {r} (vs. Occidente)"
        if term in labels:
            return str(labels[term]["label_en"]), str(labels[term]["label_es"])
        return term, term

    return f


def _latex_tables(w: _Writer, results: dict[str, Any], project: Project, root: Path) -> list[Path]:
    """Full bilingual tabular environments built from the released (SDC) tables."""
    token = w.cfg.suppression_token
    labels = project.events["events"]
    target = project.config.analysis.target_vaccine
    t1 = TableSet("PO", token)
    t1.characteristics(
        w.tables["p1_characteristics"],
        w.tables["p1_characteristics_continuous"],
        target,
        ("VA-MENGOC-BC", "VA-MENGOC-BC"),
    )
    dp = w.tables["p1_disproportionality"]
    t1.disproportionality(dp, "primary_all_other_vaccines", "DispMain", min_a=w.cfg.min_cell)
    for design in sorted(dp["design"].unique()):
        t1.disproportionality(dp, design, f"Disp {design}", min_a=None)
    t1.designs(dp, w.tables["p1_design_sizes"])
    t1.model_metrics(results["paper1"]["seriousness"].metrics)
    t1.rates(w.tables["p1_rates_target"])
    t1.lca_selection(w.tables["p1_lca_selection"])
    t1.completeness(w.tables["dq_completeness"])
    t1.plausibility(w.tables["dq_plausibility"])
    if "p1_cumulative_ic" in w.tables:
        cum = w.tables["p1_cumulative_ic"]
        t1.cumulative_ic(cum, list(dict.fromkeys(cum["event"])), labels)
    t1.logistic(w.tables["p1_seriousness_logistic"], _term_label(labels, project.vaccines.get("vaccines", {})))
    paths = [t1.write(root / "latex" / "tables_p1.tex", "Paper 1 tables")]

    def attr(a: str) -> tuple[str, str]:
        return ATTRIBUTE_NAMES["en"].get(a, a), ATTRIBUTE_NAMES["es"].get(a, a)

    def outcome(o: str) -> tuple[str, str]:
        return OUTCOME_NAMES["en"].get(o, o), OUTCOME_NAMES["es"].get(o, o)

    t2 = TableSet("PT", token)
    t2.capability(w.tables["p2_capability"], w.tables["p2_changepoints"], attr)
    t2.gee(w.tables["p2_gee_primary"], attr, outcome)
    t2.sensitivity(
        w.tables["p2_gee_primary"],
        w.tables["p2_gee_sensitivity"],
        w.tables["p2_mixed_model"],
        w.tables["p2_lot_level"],
        attr,
        outcome,
    )
    t2.power(w.tables["p2_mde"], w.tables["p2_incremental_value"], outcome)
    t2.equivalence(w.tables["p2_equivalence"], attr)
    t2.linkage(w.tables["p2_linkage_by_year"])
    t2.linkage_bias(w.tables["p2_linkage_bias"])
    t2.control_charts(w.tables["p2_control_chart_summary"], attr)
    t2.gee(w.tables["p2_gee_exploratory"], attr, outcome, name="GEEExploratory", long=True)
    paths.append(t2.write(root / "latex" / "tables_p2.tex", "Paper 2 tables"))
    return paths


def _label(labels: dict[str, Any], key: str, lang: str) -> str:
    return str(labels.get(key, {}).get(f"label_{lang}", key))


def _both(fn: Any) -> tuple[str, str]:
    return fn("en"), fn("es")


def _p1_words(
    m1: MacroSet, dp: pd.DataFrame, sig_col: str, p1: dict[str, Any], project: Project, expected: float
) -> None:
    """Data-driven wording for paper 1, so that the prose follows the results in both languages."""
    ev = project.events["events"]
    tr = p1["rates_trend"]
    if tr.get("estimable"):
        lo, hi = _num(tr["rr_lo"]), _num(tr["rr_hi"])
        m1.bilingual(
            "TrendWord",
            "increased" if lo > 1 else "decreased" if hi < 1 else "showed no significant linear trend",
            "aumentó" if lo > 1 else "disminuyó" if hi < 1 else "no mostró una tendencia lineal significativa",
        )
        plo, phi = _num(tr["pooled_rate_lo"]), _num(tr["pooled_rate_hi"])
        m1.bilingual(
            "RateVsExpected",
            "below" if phi < expected else "above" if plo > expected else "consistent with",
            "inferior a" if phi < expected else "superior a" if plo > expected else "compatible con",
        )
    prim = dp[dp["design"] == "primary_all_other_vaccines"]
    flagged = list(prim.loc[prim[sig_col].astype(bool), "event"])
    designs = sorted(dp["design"].unique())
    robust = [
        e for e in flagged if all(bool(g.set_index("event")[sig_col].get(e, False)) for _, g in dp.groupby("design"))
    ]
    m1.number("NDesigns", len(designs))
    m1.number("NSignalsRobust", len(robust))
    m1.counted("NSignalsRobustPhrase", len(robust), ("signal", "signals"), ("señal", "señales"))
    freq = p1["event_frequency"]
    tgt = freq[freq["group"] == project.config.analysis.target_vaccine].copy()
    tgt["_n"] = pd.to_numeric(tgt["n"], errors="coerce")
    ranked = [e for e in tgt.sort_values("_n", ascending=False)["event"] if e != "ev_other"]
    top = ranked[:2]  # the residual "other event" category is not informative
    en, es = _both(lambda lang: join_words([lower_first(_label(ev, e, lang)) for e in top], lang))
    m1.bilingual("TopEvents", en, es)
    exp_flag = [e for e in flagged if bool(ev.get(e, {}).get("expected", False))]
    emerging = [e for e in flagged if e not in exp_flag]
    m1.number("NSignalsExpected", len(exp_flag))
    m1.number("NSignalsEmerging", len(emerging))
    m1.counted("NSignalsExpectedPhrase", len(exp_flag), ("signal", "signals"), ("señal", "señales"))
    m1.counted("NSignalsEmergingPhrase", len(emerging), ("signal", "signals"), ("señal", "señales"))
    for name, items in (
        ("SignalList", flagged),
        ("SignalRobustList", robust),
        ("SignalExpectedList", exp_flag),
        ("SignalEmergingList", emerging),
    ):
        en, es = _both(lambda lang, items=items: join_words([lower_first(_label(ev, e, lang)) for e in items], lang))
        m1.bilingual(name, en, es)
    gt = p1.get("lca_group_test") or {}
    pv = _num(gt.get("p_value"))
    if not math.isnan(pv):
        m1.bilingual(
            "LCAGroupWord", "differed" if pv < 0.05 else "did not differ", "difirió" if pv < 0.05 else "no difirió"
        )
    met = p1["seriousness"].metrics
    auc = {k: _num(v.get("auroc")) for k, v in met.items() if k.endswith("test")}
    if auc and not all(math.isnan(v) for v in auc.values()):
        best = max(auc, key=lambda k: -math.inf if math.isnan(auc[k]) else auc[k])
        b = auc[best]
        m1.bilingual(
            "BestModel",
            "gradient boosting" if best.startswith("gbm") else "logistic regression",
            "potenciación del gradiente" if best.startswith("gbm") else "regresión logística",
        )
        m1.number("BestAuroc", b, 3)
        grade_en = "poor" if b < 0.6 else "modest" if b < 0.7 else "acceptable" if b < 0.8 else "good"
        grade_es = {"poor": "pobre", "modest": "modesta", "acceptable": "aceptable", "good": "buena"}[grade_en]
        m1.bilingual("DiscriminationWord", grade_en, grade_es)
        limited = b < 0.7
        m1.bilingual(
            "HospInterpretation",
            "Such limited discrimination is itself informative: the decision to hospitalise depends on "
            "clinical and organisational factors absent from the form"
            if limited
            else "Even with this discrimination, the form omits clinical and organisational factors that "
            "determine hospitalisation",
            "Una discriminación tan limitada es informativa en sí misma: la decisión de hospitalizar "
            "depende de factores clínicos y organizativos ausentes del formulario"
            if limited
            else "Aun con esta discriminación, el formulario omite factores clínicos y organizativos que "
            "determinan la hospitalización",
        )
    its = p1["incidence_its"]["level_change_rr"]
    lo, hi = _num(its["lo"]), _num(its["hi"])
    m1.bilingual(
        "ITSWord",
        "an abrupt fall" if hi < 1 else "an abrupt rise" if lo > 1 else "no significant step change",
        "una caída abrupta" if hi < 1 else "un aumento abrupto" if lo > 1 else "ningún cambio de nivel significativo",
    )


def _p2_words(m2: MacroSet, gee: pd.DataFrame, p2: dict[str, Any], alpha: float) -> None:
    """Data-driven wording for paper 2 (directions, lists) in both languages."""
    capall = p2["capability"][p2["capability"]["period"] == "all"]
    all_conform = bool((pd.to_numeric(capall["pct_conforming"], errors="coerce") >= 100.0).all())
    m2.bilingual(
        "ConformitySentence",
        "All lots met their release specifications"
        if all_conform
        else "Some lots had results outside their release specifications",
        "Todos los lotes cumplieron sus especificaciones de liberación"
        if all_conform
        else "Algunos lotes tuvieron resultados fuera de sus especificaciones de liberación",
    )
    m2.bilingual(
        "WithinSpecPhrase",
        "within specification" if all_conform else "mostly within specification",
        "dentro de especificación" if all_conform else "mayoritariamente dentro de especificación",
    )
    sens = p2.get("gee_sensitivity")
    single = gee[(gee["model"] == "single") & ~gee["negative_control"].astype(bool)]
    sig = single[pd.to_numeric(single["p_bh"], errors="coerce") < alpha]
    agree = total = 0
    for _, r in sig.iterrows():
        up = _num(r["or_per_sd"]) > 1
        others: list[float] = []
        if sens is not None and len(sens):
            ss = sens[(sens["outcome"] == r["outcome"]) & (sens["exposure"] == r["exposure"])]
            others += [_num(v) for v in ss.loc[ss["model"] == "single", "or_per_sd"]]
        for key in ("mixed_model", "lot_level"):
            t = p2.get(key)
            if t is not None and len(t):
                tt = t[(t["outcome"] == r["outcome"]) & (t["exposure"] == r["exposure"])]
                others += [_num(v) for v in tt["or_per_sd"]]
        for v in others:
            if not math.isnan(v):
                total += 1
                agree += int((v > 1) == up)
    m2.number("SensAgree", agree)
    m2.number("SensTotal", total)
    if total:
        m2.bilingual(
            "SensSentence",
            f"In the sensitivity analyses, {agree} of {total} estimates of the significant associations "
            "had the same direction as the primary estimate",
            f"En los análisis de sensibilidad, {agree} de {total} estimaciones de las asociaciones "
            "significativas tuvieron la misma dirección que la estimación principal",
        )
    else:
        m2.bilingual(
            "SensSentence",
            "No association was significant in the primary analysis, and the sensitivity analyses are "
            "reported for completeness",
            "Ninguna asociación fue significativa en el análisis principal, y los análisis de "
            "sensibilidad se presentan para completar la información",
        )
    single = gee[gee["model"] == "single"]
    primary = single[~single["negative_control"].astype(bool)]
    m2.number("NPrimaryTests", len(primary))
    m2.number("FDRAlpha", alpha, 2)
    sig_items: dict[str, list[str]] = {"en": [], "es": []}
    for _, r in single.iterrows():
        orr, p, q = _num(r["or_per_sd"]), _num(r["p_value"]), _num(r.get("p_bh"))
        neg = bool(r["negative_control"])
        crit = p if neg else q
        up = orr > 1
        if not math.isnan(crit) and crit < (0.05 if neg else alpha):
            en = "positively associated with" if up else "inversely associated with"
            es = "mostró una asociación positiva con" if up else "mostró una asociación inversa con"
            if not neg:
                for lang in ("en", "es"):
                    sig_items[lang].append(
                        f"{lower_first(ATTRIBUTE_NAMES[lang].get(r['exposure'], r['exposure']))}"
                        f" {'and' if lang == 'en' else 'y'} "
                        f"{lower_first(OUTCOME_NAMES[lang].get(r['outcome'], r['outcome']))}"
                    )
        elif not math.isnan(p) and p < 0.05:
            en, es = "only nominally associated with", "mostró solo una asociación nominal con"
        else:
            en, es = "not associated with", "no mostró asociación con"
        m2.bilingual(f"{r['outcome']} {r['exposure']} Dir", en, es)
    m2.bilingual("SignificantList", join_words(sig_items["en"], "en"), join_words(sig_items["es"], "es"))
    neg = single[single["negative_control"].astype(bool)]
    n_neg = int((pd.to_numeric(neg["p_value"], errors="coerce") < 0.05).sum())
    m2.number("NNegControlNominal", n_neg)
    m2.bilingual(
        "NegControlWord",
        "was associated" if n_neg else "was not associated",
        "se asoció" if n_neg else "no se asoció",
    )
    m2.bilingual(
        "NegControlSentence",
        f"The negative-control exposure was nominally associated with {n_neg} "
        f"{'outcome' if n_neg == 1 else 'outcomes'}, a warning of residual bias"
        if n_neg
        else "The negative-control exposure was not associated with any outcome",
        f"La exposición de control negativo se asoció nominalmente con {n_neg} "
        f"{'desenlace' if n_neg == 1 else 'desenlaces'}, una advertencia de sesgo residual"
        if n_neg
        else "La exposición de control negativo no se asoció con ningún desenlace",
    )
    inc = p2["incremental_value"]
    ok = inc[inc["estimable"].astype(bool)] if len(inc) else inc
    improved = bool(len(ok) and ((pd.to_numeric(ok["perm_p"]) < 0.05) & (pd.to_numeric(ok["delta_auc"]) > 0)).any())
    m2.bilingual(
        "IncrementalWord",
        "improved" if improved else "did not improve",
        "mejoró" if improved else "no mejoró",
    )
    ep = _num(p2["energy_test"]["p_value"])
    m2.bilingual(
        "EnergyWord",
        "differed" if ep < 0.05 else "did not differ",
        "difirieron" if ep < 0.05 else "no difirieron",
    )
    cap = p2["capability"]
    capall = cap[cap["period"] == "all"]
    low = [a for a, v in zip(capall["attribute"], pd.to_numeric(capall["ppk"]), strict=True) if v < 1.0]
    m2.bilingual(
        "PpkBelowOneList",
        join_words([lower_first(ATTRIBUTE_NAMES["en"].get(a, a)) for a in low], "en"),
        join_words([lower_first(ATTRIBUTE_NAMES["es"].get(a, a)) for a in low], "es"),
    )
    cps = p2["changepoints"]
    items = list(zip(cps["attribute"], cps["production_year"], strict=True)) if len(cps) else []
    m2.bilingual(
        "ChangepointList",
        join_words([f"{lower_first(ATTRIBUTE_NAMES['en'].get(a, a))} ({int(y)})" for a, y in items], "en"),
        join_words([f"{lower_first(ATTRIBUTE_NAMES['es'].get(a, a))} ({int(y)})" for a, y in items], "es"),
    )


def _figures(
    w: _Writer, results: dict[str, Any], project: Project, root: Path, synthetic: bool, extra: dict[str, Any]
) -> list[Path]:
    figs.apply_style()
    labels = project.events["events"]
    p1, p2 = results["paper1"], results["paper2"]
    target = project.config.analysis.target_vaccine
    out: list[Path] = []
    for lang in project.config.release.languages:
        fdir = root / "figures" / lang
        out.append(
            figs.fig_rates(
                {
                    "monthly_all": w.tables["p1_monthly_all"],
                    "monthly_target": w.tables["p1_monthly_target"],
                    "rates": w.tables["p1_rates_target"],
                    "breaks": p1["monthly_changepoints_all"].get("breaks", []),
                    "expected": project.config.analysis.expected_national_rate_per_100k,
                },
                lang,
                fdir / "p1_rates.pdf",
                synthetic,
            )
        )
        out.append(
            figs.fig_forest_disproportionality(
                {"table": w.tables["p1_disproportionality"], "labels": labels, "min_reports": w.cfg.min_cell},
                lang,
                fdir / "p1_forest.pdf",
                synthetic,
            )
        )
        out.append(
            figs.fig_lca(
                {
                    "profiles": w.tables["p1_lca_profiles"].dropna(subset=["probability"]),
                    "by_group": p1["lca_by_group"],
                    "labels": labels,
                    "target_label": target,
                },
                lang,
                fdir / "p1_lca.pdf",
                synthetic,
            )
        )
        if len(w.tables.get("p1_shap_importance", [])):
            term = _term_label(labels, project.vaccines.get("vaccines", {}))
            names = {f: term(f)[0 if lang == "en" else 1] for f in w.tables["p1_shap_importance"]["feature"]}
            out.append(
                figs.fig_shap(
                    {"importance": w.tables["p1_shap_importance"], "names": names},
                    lang,
                    fdir / "p1_shap.pdf",
                    synthetic,
                )
            )
        its = p1["incidence_its"]
        out.append(
            figs.fig_incidence(
                {"fitted": its["fitted"], "start": its["intervention_year"], "end": its["end_transition"]},
                lang,
                fdir / "p1_incidence.pdf",
                synthetic,
            )
        )
        names2 = ATTRIBUTE_NAMES[lang]
        out.append(
            figs.fig_qc_annual(
                {
                    "quantiles": extra["quantiles"],
                    "names": names2,
                    "changepoints": p2["changepoints"],
                    "order": list(p2["scales"]),
                    "sides": {k: v["one_sided"] for k, v in p2["scales"].items()},
                },
                lang,
                fdir / "p2_qc_annual.pdf",
                synthetic,
            )
        )
        out.append(
            figs.fig_t2(
                {"t2_quantiles": extra["t2_quantiles"], "t2_limit": p2["mspc_summary"]["t2_limit"]},
                lang,
                fdir / "p2_t2.pdf",
                synthetic,
            )
        )
        gp = w.tables["p2_gee_primary"]
        gp = gp[(gp["model"] == "single") & gp["or_per_sd"].notna()]
        out.append(
            figs.fig_forest_gee(
                {
                    "gee": gp,
                    "names": names2,
                    "outcome_names": OUTCOME_NAMES[lang],
                    "mde": dict(zip(p2["mde"]["outcome"], p2["mde"]["mde_or_per_sd"], strict=True)),
                },
                lang,
                fdir / "p2_forest.pdf",
                synthetic,
            )
        )
        if len(p2["incremental_value"]):
            out.append(
                figs.fig_incremental(
                    {"incremental": p2["incremental_value"], "outcome_names": OUTCOME_NAMES[lang]},
                    lang,
                    fdir / "p2_incremental.pdf",
                    synthetic,
                )
            )
        out.append(
            figs.fig_capability(
                {"capability": p2["capability"], "names": names2}, lang, fdir / "p2_capability.pdf", synthetic
            )
        )
        out.append(
            figs.fig_equivalence(
                {
                    "equivalence": p2["equivalence"],
                    "names": names2,
                    "margin": project.config.analysis.qc.equivalence_margin_fraction,
                },
                lang,
                fdir / "p2_equivalence.pdf",
                synthetic,
            )
        )
    return out


def _web_bundle(w: _Writer, root: Path, meta: dict[str, Any], project: Project) -> Path:
    bundle = {
        "meta": meta,
        "labels": {"events": project.events["events"], "attributes": ATTRIBUTE_NAMES, "outcomes": OUTCOME_NAMES},
        "tables": {k: _jsonable(v) for k, v in w.tables.items()},
        "objects": w.jsons,
    }
    path = root / "web" / "bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(bundle), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def build_release(project: Project, outputs: PipelineOutputs) -> Path:
    """Write ``release/<origin>/`` and return its path."""
    return build_release_from_results(project, outputs.results, outputs.run)


def build_release_from_results(project: Project, results: dict[str, Any], ctx: RunContext) -> Path:
    """Write ``release/<origin>/`` from analysis results and the provenance context of the run."""
    synthetic = ctx.synthetic
    origin = "synthetic" if synthetic else "public"
    root = project.release_dir / origin
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    w = _Writer(root, project)
    target = project.config.analysis.target_vaccine
    _dq_tables(w, results["data_quality"])
    _paper1_tables(w, results["paper1"], project.events["events"], target)
    extra = _paper2_tables(w, results["paper2"], project, project.config.sdc.release_lot_values)
    macro_paths = _macros(w, results, project, root, synthetic)
    macro_paths += _latex_tables(w, results, project, root)
    fig_paths = _figures(w, results, project, root, synthetic, extra)
    git = git_state(project.root)
    meta = {
        "data_origin": origin,
        "synthetic": synthetic,
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "run_id": ctx.run_id,
        "code_version": __version__,
        "git_commit": git.get("commit"),
        "git_dirty": git.get("dirty"),
        "seed": project.config.analysis.seed,
        "study_years": list(project.config.analysis.study_years),
        "target_vaccine": target,
        "sdc": {
            "min_cell": w.cfg.min_cell,
            "token": w.cfg.suppression_token,
            "secondary_suppression": w.cfg.secondary_suppression,
            "release_lot_values": w.cfg.release_lot_values,
        },
        "config_sha256": project.config_fingerprint(),
        "inputs_sha256": dict(sorted(ctx.inputs.items())),
    }
    (root / "tables" / "_schema.json").write_text(json.dumps(w.schema, indent=2, ensure_ascii=False), encoding="utf-8")
    web = _web_bundle(w, root, meta, project)
    (root / "README.md").write_text(_readme(meta), encoding="utf-8")
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        **meta,
        "sdc_log": {"tables": w.log.tables, "total": w.log.total()},
        "files": {str(p.relative_to(root)): _sha(p) for p in files},
        "n_tables": len(w.tables),
        "n_figures": len(fig_paths),
        "n_macro_files": len(macro_paths),
        "web_bundle": str(web.relative_to(root)),
    }
    (root / "manifest.json").write_text(json.dumps(_jsonable(manifest), indent=2, ensure_ascii=False), encoding="utf-8")
    ctx.step("build_release", rows_out=len(files), origin=origin, suppressed=w.log.total())
    for p in files:
        ctx.register_output(p)
    return root


def _readme(meta: dict[str, Any]) -> str:
    warn = (
        "> **SYNTHETIC DATA.** Every number in this directory was computed on simulated records "
        "generated by `vamengoc synth`. They are NOT results about VA-MENGOC-BC.\n\n"
        if meta["synthetic"]
        else ""
    )
    return f"""# Public release — `{meta["data_origin"]}`

{warn}Generated {meta["generated_utc"]} by vamengoc {meta["code_version"]} (commit `{meta["git_commit"]}`),
run `{meta["run_id"]}`, seed {meta["seed"]}.

This directory is the only output of the pipeline that may leave the controlled environment.
It contains aggregated, disclosure-controlled statistics:

| Folder | Content |
|---|---|
| `tables/` | CSV/JSON tables; `_schema.json` lists the person-count columns |
| `latex/` | macro files quoted by the manuscripts (never edit by hand) |
| `figures/en`, `figures/es` | vector figures for the manuscripts |
| `web/bundle.json` | data bundle for the web application and slides |
| `manifest.json` | provenance, SHA-256 of every file, disclosure-control log |

Disclosure control: person counts between 1 and {meta["sdc"]["min_cell"] - 1} are shown as
`{meta["sdc"]["token"]}`; statistics derived from a suppressed count are removed; complementary
suppression is applied to contingency tables; lot-level values are released as
`{meta["sdc"]["release_lot_values"]}`. Verify with `vamengoc release verify {meta["data_origin"]}`.
"""
