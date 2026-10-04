"""End-to-end run on synthetic data: ingestion robustness, curation, analyses, release."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import make_project
from vamengoc.config import Project
from vamengoc.pipeline import PipelineOutputs
from vamengoc.release.verify import verify_release
from vamengoc.synth import SyntheticDataset


def test_ingestion_handles_schema_drift(pipeline_run: tuple[Project, PipelineOutputs]) -> None:
    _, out = pipeline_run
    reports = out.aefi.schema_reports
    assert len(reports) == 9
    assert reports["EA_2020_TOTAL.xlsx"]["header_row"] == 2  # title row above the header
    assert "ev_purpura" in reports["EA_2023_TOTAL.xlsx"]["missing_optional"]
    assert reports["EA_2021_TOTAL.xlsx"]["unmatched_columns"][0]["header"] == "OBSERVACIONES"
    assert all(not r["missing_required"] for r in reports.values())
    st = out.aefi.staging
    assert {"full_name", "address", "birth_date", "other_text"}.isdisjoint(st.columns)
    assert st["person_id"].str.match(r"^[PW][0-9a-f]+$").all()
    assert st["vaccination_date"].notna().all()


def test_dedup_matches_generated_truth(
    pipeline_run: tuple[Project, PipelineOutputs], synthetic_dir: SyntheticDataset
) -> None:
    _, out = pipeline_run
    truth = synthetic_dir.aefi_truth
    log = out.curated.dedup_log
    n_exact = int((truth["kind"] == "exact_duplicate").sum())
    n_key = int((truth["kind"] == "key_duplicate").sum())
    assert log["rows_in"] == len(truth)
    # every planted exact duplicate is removed; a planted key duplicate can coincide with an exact one
    assert n_exact <= log["exact_duplicates_removed"] <= n_exact + n_key
    assert log["rows_out"] == log["rows_in"] - log["exact_duplicates_removed"] - log["key_duplicate_rows_merged"]
    assert log["rows_out"] <= int((truth["kind"] == "original").sum()) + 2


def test_curated_variables(pipeline_run: tuple[Project, PipelineOutputs]) -> None:
    project, out = pipeline_run
    rep = out.curated.reports
    assert rep["analytic_year"].notna().all()
    assert rep.loc[rep["in_study_window"], "analytic_year"].between(2017, 2025).all()
    assert (~rep["in_study_window"]).sum() > 0  # 2016 vaccinations in the 2017 file
    assert rep["has_target"].sum() > 50
    assert rep["coadministered"].any() and rep["target_only"].any()
    assert rep["dq_notification_before_vaccination"].any()
    assert set(rep["age_group"].dropna()) <= {"0-5", "6-14", "15-60", "61+"}
    adm = out.curated.administrations
    assert set(adm["record_id"]) == set(rep["record_id"])
    assert "AM-BC" in set(adm["vaccine"])
    assert out.curated.events["event"].nunique() == 26
    assert (project.curated_dir / "synthetic" / "reports.parquet").is_file()


def test_linkage_quality(pipeline_run: tuple[Project, PipelineOutputs]) -> None:
    _, out = pipeline_run
    s = out.linkage.summary
    assert s["link_rate"] > 0.75
    assert s["by_level"].get("exact", 0) > s["by_level"].get("core", 0) > 0


def test_analyses_present(pipeline_run: tuple[Project, PipelineOutputs]) -> None:
    _, out = pipeline_run
    p1, p2 = out.results["paper1"], out.results["paper2"]
    assert set(p1["disproportionality"]["design"]) == {
        "primary_all_other_vaccines",
        "infant_active_comparator",
        "excluding_coadministration",
        "excluding_pentavalent_masking",
    }
    assert p1["lca_best_k"] >= 2
    assert p1["rates_trend"]["estimable"]
    assert len(p2["capability"]) == 3 * 11
    assert "endotoxin" in set(p2["changepoints"]["attribute"])  # planted 2018 process shift
    assert p2["mspc_summary"]["n_lots"] == 736
    assert len(p2["gee"]) and len(p2["gee_exploratory"]) and len(p2["gee_sensitivity"])
    assert p2["equivalence"]["equivalent"].all()


def test_release_is_complete_and_clean(pipeline_run: tuple[Project, PipelineOutputs]) -> None:
    project, out = pipeline_run
    root = out.release_dir
    assert root is not None and root.name == "synthetic"
    rep = verify_release(project, root)
    assert rep.ok, rep.errors
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True and manifest["n_figures"] == 22
    for name in ("macros_common.tex", "macros_p1.tex", "macros_p2.tex"):
        text = (root / "latex" / name).read_text(encoding="utf-8")
        assert "\\newcommand" in text
    common = (root / "latex" / "macros_common.tex").read_text(encoding="utf-8")
    assert "\\newcommand{\\VDataOrigin}{synthetic}" in common
    bundle = json.loads((root / "web" / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["meta"]["data_origin"] == "synthetic" and "p1_disproportionality" in bundle["tables"]
    dp = pd.read_csv(root / "tables" / "p1_disproportionality.csv")
    small = dp["a"].astype(str) == "<5"
    assert dp.loc[small, "ror"].isna().all()
    assert (out.run.run_dir / "manifest.json").is_file()
    local = out.run.run_dir / "local_only"
    assert (local / "README.txt").is_file() and not str(local).startswith(str(root))
    assert (local / "results.pkl").is_file()
    specs = json.loads((root / "tables" / "p2_specifications.json").read_text(encoding="utf-8"))
    scales = json.loads((root / "tables" / "p2_scales.json").read_text(encoding="utf-8"))
    assert all(set(v) == {"op"} for v in specs.values())  # no absolute limits or units released
    assert all(set(v) == {"transform", "one_sided"} for v in scales.values())
    p1 = (root / "latex" / "macros_p1.tex").read_text(encoding="utf-8")
    p2 = (root / "latex" / "macros_p2.tex").read_text(encoding="utf-8")
    for name in ("POTrendWord", "PORateVsExpected", "POSignalList", "POBestModel", "POITSWord"):
        assert f"\\newcommand{{\\{name}}}{{\\VLang{{" in p1, name
    for name in ("PTSignificantList", "PTNegControlWord", "PTIncrementalWord", "PTEnergyWord", "PTChangepointList"):
        assert f"\\newcommand{{\\{name}}}{{\\VLang{{" in p2, name


def test_release_rebuild_from_snapshot(pipeline_run: tuple[Project, PipelineOutputs]) -> None:
    from vamengoc.pipeline import load_results_snapshot, rebuild_release

    project, out = pipeline_run
    snap = load_results_snapshot(project)
    assert snap["synthetic"] is True and snap["run_id"] == out.run.run_id
    assert load_results_snapshot(project, out.run.run_id)["run_id"] == out.run.run_id
    before = (out.release_dir / "latex" / "macros_p2.tex").read_text(encoding="utf-8")  # type: ignore[operator]
    root = rebuild_release(project)
    assert verify_release(project, root).ok
    assert (root / "latex" / "macros_p2.tex").read_text(encoding="utf-8") == before
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs_sha256"] == dict(sorted(out.run.inputs.items()))


def test_snapshot_errors(tmp_path: Path) -> None:
    from vamengoc.pipeline import SNAPSHOT_NAME, load_results_snapshot

    project = make_project(tmp_path)
    with pytest.raises(FileNotFoundError, match="no results snapshot"):
        load_results_snapshot(project)
    run = project.runs_dir / "20000101T000000Z-aaaaaa"
    (run / "local_only").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="has no results snapshot"):
        load_results_snapshot(project, run.name)
    import pickle

    (run / "local_only" / SNAPSHOT_NAME).write_bytes(pickle.dumps({"format": 99}))
    with pytest.raises(ValueError, match="unsupported snapshot format"):
        load_results_snapshot(project, run.name)
