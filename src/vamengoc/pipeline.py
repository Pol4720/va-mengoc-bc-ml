"""End-to-end pipeline: ingest → curate → analyse → release.

Two phases (see docs/DATA_GOVERNANCE.md):

* **Phase 1 (local, restricted data).** Run on the raw files inside the
  controlled environment. Produces the pseudonymised curated layer (local,
  never versioned), the full-detail results (local) and the public release
  (aggregated, disclosure-controlled) that the data owner reviews before
  committing.
* **Phase 2 (public).** Manuscripts, reports, slides and the web app are
  built only from the committed release.
"""

from __future__ import annotations

import json
import pickle
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from vamengoc.analysis import descriptive, disproportionality, lca, rates, seriousness, spc, timeseries
from vamengoc.analysis.equivalence import energy_test, hodges_lehmann, tost_welch
from vamengoc.analysis.mspc import fit_mspc, flagged_summary, top_contributors
from vamengoc.analysis.qc_safety import (
    build_qc_safety_frame,
    gee_family,
    incremental_value,
    lot_level_models,
    minimum_detectable_or,
    mixed_model_sensitivity,
)
from vamengoc.config import Project
from vamengoc.curate.aefi_model import CuratedAEFI, curate_aefi, event_columns
from vamengoc.curate.linkage import LinkageResult, link_reports_to_lots
from vamengoc.curate.quality import completeness_table, conformance_table, plausibility_table
from vamengoc.ingest.aefi import AEFIIngestResult, ingest_aefi, schema_drift
from vamengoc.ingest.lots import LotsIngestResult, find_lots_workbook, ingest_lots_workbook
from vamengoc.normalize.registry import build_normalizers
from vamengoc.provenance import RunContext
from vamengoc.security import crypto
from vamengoc.security.pseudonymize import Pseudonymizer, load_key
from vamengoc.synth import MARKER_FILE

__all__ = ["PipelineOutputs", "is_synthetic_dir", "load_results_snapshot", "rebuild_release", "run_pipeline"]

SNAPSHOT_NAME = "results.pkl"


@dataclass
class PipelineOutputs:
    run: RunContext
    aefi: AEFIIngestResult
    lots: LotsIngestResult
    curated: CuratedAEFI
    linkage: LinkageResult
    results: dict[str, Any] = field(default_factory=dict)
    release_dir: Path | None = None


def is_synthetic_dir(directory: Path) -> bool:
    return (directory / MARKER_FILE).is_file()


# ---------------------------------------------------------------------------------------
# Paper 1 — national pharmacovigilance of VA-MENGOC-BC
# ---------------------------------------------------------------------------------------
def analyze_paper1(project: Project, cur: CuratedAEFI, lots: LotsIngestResult, ctx: RunContext) -> dict[str, Any]:
    a = project.config.analysis
    target = a.target_vaccine
    rep = cur.reports[cur.reports["in_study_window"]].copy()
    ev_cols = event_columns(rep)
    labels = project.events["events"]
    out: dict[str, Any] = {}

    out["characteristics"] = descriptive.characteristics_table(rep, target)
    out["characteristics_continuous"] = out["characteristics"].attrs.get("continuous")
    out["event_frequency"] = descriptive.event_frequency_table(rep, target, labels)
    out["reports_by_year"] = descriptive.reports_by_year(rep, target)

    # Reporting rates per 100 000 doses (target vaccine only: the only denominator available).
    by_year = out["reports_by_year"]
    doses = lots.coverage.rename(columns={"doses_administered": "doses_administered"})
    out["rates_all_target"] = rates.annual_reporting_rates(
        by_year, doses, count_col="n_target", expected_rate=a.expected_national_rate_per_100k
    )
    out["rates_trend"] = rates.rate_trend(out["rates_all_target"])
    ev_year = []
    for ev in [
        "ev_fever_39",
        "ev_fever_40",
        "ev_severe_local_reaction",
        "ev_persistent_crying",
        "ev_febrile_seizure",
        "ev_collapse",
        "ev_allergic_reaction",
    ]:
        if ev not in rep:
            continue
        cnt = (
            rep[rep["has_target"]]
            .assign(_e=rep[ev].astype("boolean").fillna(False))
            .groupby("analytic_year")["_e"]
            .sum()
            .rename("count")
            .reset_index()
        )
        r = rates.annual_reporting_rates(cnt, doses, count_col="count")
        r["event"] = ev
        ev_year.append(r)
    out["rates_by_event"] = pd.concat(ev_year, ignore_index=True) if ev_year else pd.DataFrame()
    hosp = (
        rep[rep["has_target"]]
        .assign(_h=rep["hospitalized"].astype("boolean").fillna(False))
        .groupby("analytic_year")["_h"]
        .sum()
        .rename("count")
        .reset_index()
    )
    out["rates_hospitalized"] = rates.annual_reporting_rates(hosp, doses, count_col="count")

    # Disproportionality under the primary and sensitivity comparators.
    dp = a.disproportionality
    crit = dp.model_dump()
    primary_criterion = str(crit.pop("primary_criterion"))
    is_t = rep["has_target"]
    vac = rep["vaccines"].fillna("")
    infant = rep["age_months"].astype("Float64").lt(a.infant_comparator_max_age_months + 1).fillna(False)
    designs = {
        "primary_all_other_vaccines": (is_t, ~is_t),
        "infant_active_comparator": (is_t & infant, ~is_t & infant),
        "excluding_coadministration": (rep["target_only"], ~is_t & ~rep["coadministered"]),
        "excluding_pentavalent_masking": (is_t, ~is_t & ~vac.str.contains("PENTA-L", regex=False)),
    }
    counts = disproportionality.vaccine_event_counts(cur.administrations, cur.events, rep["record_id"])
    out["n_vaccines"] = int(counts["vaccine"].nunique())
    prior = disproportionality.fit_mgps_prior(counts["n"].to_numpy(), counts["expected"].to_numpy())
    out["mgps_prior"] = {
        "alpha1": prior.alpha1,
        "beta1": prior.beta1,
        "alpha2": prior.alpha2,
        "beta2": prior.beta2,
        "p": prior.p,
        "converged": prior.converged,
        "loglik": prior.loglik,
        "n_cells": len(counts),
    }
    tables = []
    for name, (t_mask, c_mask) in designs.items():
        tab = disproportionality.disproportionality_table(
            rep,
            t_mask,
            c_mask,
            ev_cols,
            prior=prior if name.startswith("primary") else None,
            criteria=crit,
            primary=primary_criterion,
        )
        tab["design"] = name
        tables.append(tab)
    out["disproportionality"] = pd.concat(tables, ignore_index=True)
    years = sorted(int(y) for y in rep["analytic_year"].dropna().unique())
    top = (
        out["disproportionality"]
        .query("design == 'primary_all_other_vaccines'")
        .sort_values("a", ascending=False)["event"]
        .head(4)
        .tolist()
    )
    prim_tab = out["disproportionality"].query("design == 'primary_all_other_vaccines'")
    top += [e for e in prim_tab.loc[prim_tab["signal_primary"].astype(bool), "event"] if e not in top]
    out["cumulative_ic"] = (
        pd.concat([disproportionality.cumulative_ic(rep, is_t, ~is_t, e, years) for e in top], ignore_index=True)
        if top
        else pd.DataFrame()
    )

    # Latent reactogenicity phenotypes.
    prev = rep[ev_cols].astype("boolean").fillna(False).mean()
    items = [e for e in ev_cols if prev[e] >= 0.005]
    lc = a.lca
    sel = lca.select_lca(
        rep[items],
        (lc.k_range[0], lc.k_range[1]),
        n_starts=lc.n_starts,
        max_iter=lc.max_iter,
        tol=lc.tol,
        seed=a.seed,
        bootstrap=lc.bootstrap,
    )
    fit = sel["fit"]
    out["lca_selection"] = sel["table"]
    out["lca_best_k"] = sel["best_k"]
    out["lca_bootstrap_ari_median"] = sel["bootstrap_ari_median"]
    out["lca_profiles"] = lca.class_profiles(fit, items)
    rep["lca_class"] = fit.assign() + 1
    group = np.where(is_t, target, "Other vaccines")
    ct = pd.crosstab(rep["lca_class"], group)
    out["lca_by_group"] = ct.reset_index().melt(id_vars="lca_class", var_name="group", value_name="n")
    from scipy.stats import chi2_contingency

    if ct.shape[1] == 2 and ct.shape[0] > 1:
        chi2, pval, dof, _ = chi2_contingency(ct.to_numpy())
        out["lca_group_test"] = {"chi2": float(chi2), "dof": int(dof), "p_value": float(pval)}
    out["cooccurrence_target"] = timeseries.cooccurrence(rep[is_t], ev_cols)

    # Hospitalisation model.
    sm_cfg = a.seriousness_model
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        ser = seriousness.fit_seriousness(
            rep,
            train_years=(sm_cfg.train_years[0], sm_cfg.train_years[1]),
            test_years=(sm_cfg.test_years[0], sm_cfg.test_years[1]),
            params=sm_cfg.model_dump(),
            seed=a.seed,
        )
    out["seriousness"] = ser

    # Timeliness and temporal structure.
    delay = rep[rep["notification_delay_days"].ge(0).fillna(False)]
    out["notification_delay_by_year"] = (
        delay.groupby("analytic_year")["notification_delay_days"]
        .describe(percentiles=[0.25, 0.5, 0.75, 0.9])
        .reset_index()
    )
    ms_all = timeseries.monthly_series(rep)
    ms_t = timeseries.monthly_series(rep, is_t)
    out["monthly_all"] = ms_all
    out["monthly_target"] = ms_t
    out["monthly_changepoints_all"] = timeseries.monthly_changepoints(ms_all)
    out["monthly_changepoints_target"] = timeseries.monthly_changepoints(ms_t)
    out["incidence_its"] = timeseries.incidence_its(lots.incidence)
    out["incidence"] = lots.incidence
    out["coverage"] = lots.coverage
    ctx.step("analyze_paper1", rows_in=len(rep), lca_k=sel["best_k"], designs=len(designs))
    return out


# ---------------------------------------------------------------------------------------
# Paper 2 — lot-release quality and post-marketing reactogenicity
# ---------------------------------------------------------------------------------------
def capability_periods(
    configured: list[tuple[int, int]] | None, years: pd.Series, study_start: int
) -> list[tuple[int, int]]:
    """Production periods compared in the capability analysis.

    Default: lots produced before the pharmacovigilance window and lots produced during it. The
    split is fixed by the study design, never chosen from the quality-control data.
    """
    if configured:
        return [(int(lo), int(hi)) for lo, hi in configured]
    first, last = int(years.min()), int(years.max())
    if first >= study_start or last < study_start:
        return []
    return [(first, study_start - 1), (study_start, last)]


def analyze_paper2(
    project: Project, cur: CuratedAEFI, lots: LotsIngestResult, link: LinkageResult, ctx: RunContext
) -> dict[str, Any]:
    a = project.config.analysis
    qc = a.qc
    lot_df = lots.lots.sort_values(["production_year", "source_row"]).reset_index(drop=True)
    scales = spc.attribute_scales(lots.specs, lot_df, project.lots_schema["lots_sheet"])
    out: dict[str, Any] = {
        "scales": {
            k: {
                "transform": v.transform,
                "low": v.low,
                "high": v.high,
                "window_low": v.window_low,
                "window_high": v.window_high,
                "one_sided": v.one_sided,
                "spec": v.spec.as_dict(),
            }
            for k, v in scales.items()
        }
    }
    # Capability overall and by period.
    cap_rows = []
    periods = {"all": lot_df.index == lot_df.index}
    years = lot_df["production_year"].astype(int)
    for lo, hi in capability_periods(qc.capability_periods, years, a.study_years[0]):
        periods[f"{lo}-{hi}"] = years.between(lo, hi).to_numpy()
    for pname, mask in periods.items():
        for name, sc in scales.items():
            vals = lot_df.loc[mask, name].to_numpy(dtype=float)
            c = spc.capability(vals, sc, n_boot=qc.capability_bootstrap, seed=a.seed)
            c["period"] = pname
            cap_rows.append(c)
    out["capability"] = pd.DataFrame.from_records(cap_rows)

    # Control charts and change points on the production sequence.
    charts, cps, chart_summary = [], [], []
    for name, sc in scales.items():
        t = spc.transform_values(lot_df[name].to_numpy(dtype=float), sc.transform)
        ok = np.isfinite(t)
        ch = spc.control_chart(t[ok], ewma_lambda=qc.ewma_lambda)
        ch["attribute"] = name
        ch["seq"] = np.arange(1, ok.sum() + 1)
        ch["production_year"] = years.to_numpy()[ok]
        ch["window_position"] = spc.to_window(lot_df.loc[ok, name].to_numpy(dtype=float), sc)
        charts.append(ch)
        chart_summary.append(
            {
                "attribute": name,
                "n": int(ok.sum()),
                **{r: int(ch[r].sum()) for r in ("rule1", "rule2", "rule3", "rule5")},
                "ewma_signals": int(ch["ewma_signal"].sum()),
            }
        )
        pen = qc.changepoint_penalty
        for b in spc.changepoints(t[ok], penalty=pen):
            cps.append(
                {
                    "attribute": name,
                    "index": b,
                    "production_year": int(years.to_numpy()[ok][b]),
                    "mean_before": float(np.mean(t[ok][:b])),
                    "mean_after": float(np.mean(t[ok][b:])),
                }
            )
    out["control_charts"] = pd.concat(charts, ignore_index=True)
    out["control_chart_summary"] = pd.DataFrame.from_records(chart_summary)
    out["changepoints"] = pd.DataFrame.from_records(
        cps, columns=["attribute", "index", "production_year", "mean_before", "mean_after"]
    )

    # Multivariate SPC on the analysis scales.
    mat = pd.DataFrame(
        {name: spc.transform_values(lot_df[name].to_numpy(dtype=float), sc.transform) for name, sc in scales.items()},
        index=lot_df["lot_key"],
    )
    mat = mat.replace([np.inf, -np.inf], np.nan)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ms = fit_mspc(mat, alpha=qc.mspc_alpha, seed=a.seed)
    out["mspc_notes"] = ms.notes + sorted({str(w.message)[:200] for w in caught})
    out["mspc_scores"] = ms.scores.reset_index().rename(columns={"index": "lot_key"})
    out["mspc_scores"]["production_year"] = (
        lot_df.set_index("lot_key").loc[ms.scores.index, "production_year"].to_numpy()
    )
    out["mspc_scores"]["national"] = lot_df.set_index("lot_key").loc[ms.scores.index, "national"].to_numpy()
    out["mspc_summary"] = {
        "n_components": ms.n_components,
        "explained_variance": ms.explained_variance.tolist(),
        "t2_limit": ms.t2_limit,
        "spe_limit": ms.spe_limit,
        "n_lots": len(ms.scores),
        "t2_flagged": int(ms.scores["t2_flag"].sum()),
        "spe_flagged": int(ms.scores["spe_flag"].sum()),
        **top_contributors(ms),
    }
    out["mspc_loadings"] = ms.loadings.reset_index().rename(columns={"index": "attribute"})
    out["mspc_by_year"] = flagged_summary(ms, lot_df.set_index("lot_key")["production_year"])
    corr = mat.corr(method="spearman")
    out["attribute_correlation"] = corr.reset_index().rename(columns={"index": "attribute"})

    # Destination consistency (national vs export) on the window scale.
    eq_rows = []
    nat = lot_df["national"].to_numpy()
    for name, sc in scales.items():
        w = spc.to_window(lot_df[name].to_numpy(dtype=float), sc)
        tost = tost_welch(w[nat], w[~nat], margin=qc.equivalence_margin_fraction)
        hl = hodges_lehmann(w[nat], w[~nat])
        eq_rows.append({"attribute": name, **tost, **{f"hl_{k}": v for k, v in hl.items()}})
    out["equivalence"] = pd.DataFrame.from_records(eq_rows)
    wmat = np.column_stack([spc.to_window(lot_df[n].to_numpy(dtype=float), s) for n, s in scales.items()])
    okrows = np.all(np.isfinite(wmat), axis=1)
    out["energy_test"] = energy_test(wmat[okrows & nat], wmat[okrows & ~nat], n_perm=499, seed=a.seed)

    # Linkage and quality-safety models.
    out["linkage_summary"] = link.summary
    out["linkage_bias"] = link.bias_table
    qs = a.qc_safety
    exposures = [
        *qs.primary_exposures,
        *[e for e in scales if e not in qs.primary_exposures and e not in qs.negative_control_exposures],
        *qs.negative_control_exposures,
        "atypicality_t2",
    ]
    reports = cur.reports[cur.reports["in_study_window"]]
    atyp = ms.scores["t2"]
    frame = build_qc_safety_frame(reports, link.links, lot_df, scales, exposures, atypicality=atyp)
    outcomes = [o for o in [*qs.primary_outcomes, *qs.secondary_outcomes] if o in frame.data]
    out["qc_frame_summary"] = {
        "n_reports": len(frame.data),
        "n_lots": frame.n_lots,
        "exposures": frame.exposures,
        "exposure_sd": frame.exposure_sd,
        "covariates": frame.covariate_terms,
        "notes": frame.notes,
        "reports_per_lot": frame.data.groupby("lot_key").size().describe().to_dict(),
    }
    primary_frame = build_qc_safety_frame(
        reports, link.links, lot_df, scales, [*qs.primary_exposures, *qs.negative_control_exposures]
    )
    # Prespecified family: primary outcomes x primary exposures (+ negative control),
    # exchangeable GEE; FDR controlled within the family.
    out["gee"] = gee_family(
        primary_frame,
        list(qs.primary_outcomes),
        cov_struct=qs.gee_cov_struct,
        negative_controls=qs.negative_control_exposures,
        adjust_set=list(qs.primary_exposures),
        crude=True,
    )
    # Exploratory family: every outcome x every attribute (and T2 atypicality),
    # independence working correlation with cluster-robust SEs; separate FDR.
    out["gee_exploratory"] = gee_family(
        frame,
        outcomes,
        cov_struct="independence",
        negative_controls=qs.negative_control_exposures,
        adjust_set=list(qs.primary_exposures),
    )
    out["mixed_model"] = mixed_model_sensitivity(primary_frame, list(qs.primary_outcomes))
    out["lot_level"] = lot_level_models(primary_frame, list(qs.primary_outcomes))
    out["mde"] = pd.DataFrame(
        [
            {"outcome": o, **minimum_detectable_or(primary_frame, o)}
            for o in qs.primary_outcomes
            if o in primary_frame.data
        ]
    )
    sens = []
    sens_specs: dict[str, dict[str, Any]] = {
        "exact_links_only": {"restrict_levels": ("exact",)},
        "excluding_coadministration": {"exclude_coadministered": True},
        "keeping_temporally_implausible": {"drop_temporal_implausible": False},
    }
    for label, kw in sens_specs.items():
        f = build_qc_safety_frame(reports, link.links, lot_df, scales, list(qs.primary_exposures), **kw)
        g = gee_family(f, list(qs.primary_outcomes), cov_struct=qs.gee_cov_struct, adjust_set=[])
        g["sensitivity"] = label
        sens.append(g)
    out["gee_sensitivity"] = pd.concat(sens, ignore_index=True) if sens else pd.DataFrame()
    inc = [
        incremental_value(primary_frame, o, folds=qs.cv_folds, n_perm=qs.permutation_tests, seed=a.seed)
        for o in qs.primary_outcomes
        if o in primary_frame.data
    ]
    out["incremental_value"] = pd.DataFrame.from_records(inc)
    ctx.step("analyze_paper2", rows_in=len(frame.data), lots=frame.n_lots)
    return out


# ---------------------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------------------
def _save_local(
    project: Project,
    ctx: RunContext,
    cur: CuratedAEFI,
    lots: LotsIngestResult,
    link: LinkageResult,
    aefi: AEFIIngestResult,
) -> None:
    """Persist the curated layer and local-only diagnostics (never released)."""
    sec = project.config.security
    fernet = crypto.load_fernet(sec.fernet_key_env, sec.fernet_key_file) if sec.encrypt_curated else None
    cdir = project.curated_dir / ("synthetic" if ctx.synthetic else "real")
    for name, df in {
        "reports": cur.reports,
        "administrations": cur.administrations,
        "events": cur.events,
        "history": cur.history,
        "outcomes": cur.outcomes,
        "lots": lots.lots,
        "lot_destinations": lots.lot_destinations,
        "incidence": lots.incidence,
        "coverage": lots.coverage,
        "coverage_cumulative": lots.coverage_cumulative,
        "links": link.links,
    }.items():
        crypto.write_parquet(_parquet_safe(df), cdir / name, fernet)
    local = ctx.run_dir / "local_only"
    local.mkdir(parents=True, exist_ok=True)
    (local / "README.txt").write_text("LOCAL ONLY — may contain free-text tokens. Never publish.\n", encoding="utf-8")
    (local / "schema_reports.json").write_text(
        json.dumps(aefi.schema_reports, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (local / "normalisation_local.json").write_text(
        json.dumps(aefi.local_only, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _save_results_snapshot(project: Project, ctx: RunContext, results: dict[str, Any]) -> Path:
    """Keep the analysis results locally so the release can be rebuilt without re-running the analysis.

    The snapshot lives in ``runs/<id>/local_only`` (never versioned) and is encrypted with the
    curated-layer key when ``security.encrypt_curated`` is enabled.
    """
    sec = project.config.security
    payload = pickle.dumps(
        {
            "format": 1,
            "run_id": ctx.run_id,
            "synthetic": ctx.synthetic,
            "inputs": dict(ctx.inputs),
            "config_sha256": project.config_fingerprint(),
            "results": results,
        },
        protocol=pickle.HIGHEST_PROTOCOL,
    )
    name = SNAPSHOT_NAME
    if sec.encrypt_curated:
        payload = crypto.load_fernet(sec.fernet_key_env, sec.fernet_key_file).encrypt(payload)
        name += ".enc"
    path = ctx.run_dir / "local_only" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def load_results_snapshot(project: Project, run_id: str | None = None) -> dict[str, Any]:
    """Load the snapshot of ``run_id`` (default: the most recent run that has one).

    Snapshots are produced by this pipeline on the same workstation; they are trusted local files
    (pickle must never be used on files from elsewhere).
    """
    runs = project.runs_dir
    candidates = (
        [runs / run_id]
        if run_id
        else sorted(
            (d for d in runs.iterdir() if d.is_dir() and any((d / "local_only").glob(SNAPSHOT_NAME + "*"))),
            key=lambda d: d.name,
        )
        if runs.is_dir()
        else []
    )
    if not candidates:
        msg = "no results snapshot found; run `vamengoc run` or `vamengoc demo` first"
        raise FileNotFoundError(msg)
    local = candidates[-1] / "local_only"
    plain, enc = local / SNAPSHOT_NAME, local / (SNAPSHOT_NAME + ".enc")
    if enc.is_file():
        sec = project.config.security
        data = crypto.load_fernet(sec.fernet_key_env, sec.fernet_key_file).decrypt(enc.read_bytes())
    elif plain.is_file():
        data = plain.read_bytes()
    else:
        msg = f"run {candidates[-1].name} has no results snapshot"
        raise FileNotFoundError(msg)
    snap: dict[str, Any] = pickle.loads(data)  # noqa: S301 - trusted local artefact written by _save_results_snapshot
    if snap.get("format") != 1:
        msg = f"unsupported snapshot format {snap.get('format')!r}"
        raise ValueError(msg)
    return snap


def rebuild_release(project: Project, run_id: str | None = None) -> Path:
    """Rebuild ``release/<origin>`` from a stored results snapshot (tables, macros, figures, bundle)."""
    from vamengoc.release.builder import build_release_from_results

    snap = load_results_snapshot(project, run_id)
    ctx = RunContext(project, "release-rebuild", synthetic=bool(snap["synthetic"]))
    ctx.inputs.update(snap["inputs"])
    ctx.step(
        "load_results_snapshot",
        source_run=snap["run_id"],
        config_changed=snap["config_sha256"] != project.config_fingerprint(),
    )
    if snap["config_sha256"] != project.config_fingerprint():
        ctx.warn("configuration changed since the analysis run; analysis settings in the release are the old ones")
    root = build_release_from_results(project, snap["results"], ctx)
    ctx.close()
    return root


def _parquet_safe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
    return out


def run_pipeline(
    project: Project, input_dir: Path, *, command: str = "run", build_release: bool = True
) -> PipelineOutputs:
    """Run every stage on ``input_dir`` (raw data or a synthetic directory)."""
    synthetic = is_synthetic_dir(input_dir)
    ctx = RunContext(project, command, synthetic=synthetic)
    sec = project.config.security
    key = load_key(sec.hmac_key_env, sec.hmac_key_file, synthetic=synthetic)
    pseudo = Pseudonymizer(key)
    norm = build_normalizers(project)

    aefi = ingest_aefi(project, input_dir, norm, pseudo, ctx)
    lots = ingest_lots_workbook(
        project, find_lots_workbook(input_dir, project.config.inputs.lots_file_pattern), norm, ctx
    )
    cur = curate_aefi(aefi.staging, project, ctx)
    link = link_reports_to_lots(cur.reports, lots.lots, project, ctx)
    _save_local(project, ctx, cur, lots, link, aefi)

    results: dict[str, Any] = {
        "data_quality": {
            "schema_drift": schema_drift(aefi.schema_reports),
            "schema_reports": {
                f: {k: v for k, v in r.items() if k != "mapping"} for f, r in aefi.schema_reports.items()
            },
            "dedup": cur.dedup_log,
            "plausibility": plausibility_table(cur.reports),
            "conformance": conformance_table(aefi.parse_status),
            "completeness": completeness_table(
                cur.reports,
                [
                    "sex",
                    "age_months",
                    "province",
                    "vaccines",
                    "doses",
                    "lots_exact",
                    "manufacturers",
                    "notification_date",
                    "place",
                ],
            ),
            "lots_sheet": {k: v for k, v in lots.spec_report.items() if k != "mapping"},
            "series_reports": {
                k: {kk: vv for kk, vv in v.items() if kk != "mapping"} for k, v in lots.reports.items() if k != "lots"
            },
            "provenance_notes": lots.provenance_notes,
            "normalisation": {
                "vaccine": norm.vaccine.log.summary(),
                "manufacturer": norm.manufacturer.log.summary(),
                "province": norm.province.log.summary(),
                "place": norm.place.log.summary(),
                "destination": norm.destination.log.summary(),
            },
            "window": {
                "n_reports_total": len(cur.reports),
                "n_in_window": int(cur.reports["in_study_window"].sum()),
                "n_outside_window": int((~cur.reports["in_study_window"]).sum()),
                "n_year_differs_from_file": int(cur.reports["year_differs_from_file"].sum()),
            },
        },
    }
    results["paper1"] = analyze_paper1(project, cur, lots, ctx)
    results["paper2"] = analyze_paper2(project, cur, lots, link, ctx)
    _save_results_snapshot(project, ctx, results)
    outputs = PipelineOutputs(run=ctx, aefi=aefi, lots=lots, curated=cur, linkage=link, results=results)
    if build_release:
        from vamengoc.release.builder import build_release as _build

        outputs.release_dir = _build(project, outputs)
    ctx.close()
    return outputs
