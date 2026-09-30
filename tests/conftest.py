"""Shared fixtures: a small synthetic dataset and one full pipeline run.

Everything is generated in temporary directories; no test ever reads data/raw.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vamengoc.config import Project
from vamengoc.pipeline import PipelineOutputs, run_pipeline
from vamengoc.synth import SyntheticDataset, generate_synthetic_dataset

FAST_OVERRIDES = {
    "analysis": {
        "lca": {"k_range": [1, 4], "n_starts": 4, "bootstrap": 2, "max_iter": 300},
        "qc": {"capability_bootstrap": 100},
        "qc_safety": {"permutation_tests": 5, "cv_folds": 3},
        "seriousness_model": {"n_estimators": 60},
    },
}


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Isolate every test from any key present on the developer machine."""
    fake_home = tmp_path_factory.getbasetemp() / "fake-home"
    monkeypatch.delenv("VAMENGOC_HMAC_KEY", raising=False)
    monkeypatch.delenv("VAMENGOC_FERNET_KEY", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory: pytest.TempPathFactory) -> SyntheticDataset:
    out = tmp_path_factory.mktemp("synthetic-input")
    return generate_synthetic_dataset(out, scale=0.04, seed=123)


def make_project(tmp: Path, extra: dict | None = None) -> Project:
    from vamengoc.config import deep_merge

    paths = {
        "paths": {
            "release_dir": str(tmp / "release"),
            "runs_dir": str(tmp / "runs"),
            "curated_dir": str(tmp / "curated"),
            "synthetic_dir": str(tmp / "synthetic"),
            "interim_dir": str(tmp / "interim"),
        },
        "security": {"hmac_key_file": str(tmp / "no-such-key"), "fernet_key_file": str(tmp / "no-such-fernet")},
    }
    over = deep_merge(deep_merge(FAST_OVERRIDES, paths), extra or {})
    return Project(overrides=over)


@pytest.fixture(scope="session")
def pipeline_run(
    synthetic_dir: SyntheticDataset, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Project, PipelineOutputs]:
    tmp = tmp_path_factory.mktemp("pipeline")
    project = make_project(tmp)
    outputs = run_pipeline(project, synthetic_dir.directory)
    return project, outputs
