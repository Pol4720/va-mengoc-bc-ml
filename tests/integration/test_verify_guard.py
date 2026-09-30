"""The release guard must catch every kind of planted leak."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from vamengoc.config import Project
from vamengoc.pipeline import PipelineOutputs
from vamengoc.release.verify import verify_release


@pytest.fixture
def release_copy(pipeline_run: tuple[Project, PipelineOutputs], tmp_path: Path) -> tuple[Project, Path]:
    project, out = pipeline_run
    assert out.release_dir is not None
    dst = tmp_path / "synthetic"
    shutil.copytree(out.release_dir, dst)
    return project, dst


def _refresh_manifest(root: Path, rel: str) -> None:
    import hashlib

    m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    m["files"][rel] = hashlib.sha256((root / rel).read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(m), encoding="utf-8")


def test_clean_copy_passes(release_copy: tuple[Project, Path]) -> None:
    project, root = release_copy
    assert verify_release(project, root).ok


def test_detects_small_counts(release_copy: tuple[Project, Path]) -> None:
    project, root = release_copy
    p = root / "tables" / "p1_reports_by_year.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    row = lines[1].split(",")
    row[header.index("n_target")] = "3"
    lines[1] = ",".join(row)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _refresh_manifest(root, "tables/p1_reports_by_year.csv")
    rep = verify_release(project, root)
    assert any("small person count n_target=3" in e for e in rep.errors)


def test_detects_forbidden_columns_patterns_dates(release_copy: tuple[Project, Path]) -> None:
    project, root = release_copy
    (root / "tables" / "leak.csv").write_text("person_id,when\nP1,2017-03-04\n", encoding="utf-8")
    (root / "tables" / "leak.json").write_text(json.dumps({"x": {"full_name": "A"}}), encoding="utf-8")
    (root / "notes.md").write_text("NOMBRES Y APELLIDOS de la persona\n", encoding="utf-8")
    (root / "data.xlsx").write_bytes(b"PK")
    rep = verify_release(project, root)
    text = "\n".join(rep.errors)
    assert "forbidden columns ['person_id']" in text
    assert "day-precision date" in text
    assert "forbidden key 'full_name'" in text
    assert "forbidden pattern" in text
    assert "file type not allowed" in text
    assert "not listed in manifest" in text


def test_detects_tampering_and_origin(release_copy: tuple[Project, Path], tmp_path: Path) -> None:
    project, root = release_copy
    p = root / "tables" / "p1_lca_selection.csv"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert any("checksum mismatch" in e for e in verify_release(project, root).errors)
    renamed = tmp_path / "public"
    shutil.copytree(root, renamed)
    assert any("does not match directory" in e for e in verify_release(project, renamed).errors)
    (renamed / "manifest.json").unlink()
    assert "manifest.json missing" in verify_release(project, renamed).errors
    assert not verify_release(project, tmp_path / "nope").ok


def test_detects_bundle_leak(release_copy: tuple[Project, Path]) -> None:
    project, root = release_copy
    b = root / "web" / "bundle.json"
    obj = json.loads(b.read_text(encoding="utf-8"))
    obj["tables"]["p1_reports_by_year"][0]["n_target"] = 2
    obj["tables"]["p1_reports_by_year"][0]["record_id"] = "R1"
    b.write_text(json.dumps(obj), encoding="utf-8")
    _refresh_manifest(root, "web/bundle.json")
    text = "\n".join(verify_release(project, root).errors)
    assert "small person count in p1_reports_by_year[0].n_target=2" in text
    assert "forbidden key 'record_id'" in text
    (root / "tables" / "bad.json").write_text("{not json", encoding="utf-8")
    assert any("invalid JSON" in e for e in verify_release(project, root).errors)
