"""Command-line interface."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vamengoc import __version__
from vamengoc.cli import _parse_overrides, app
from vamengoc.synth import SyntheticDataset

runner = CliRunner()


def test_version_and_overrides() -> None:
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and __version__ in r.stdout
    assert _parse_overrides(["analysis.seed=3", "sdc.min_cell=10", "x.y=[1, 2]"]) == {
        "analysis": {"seed": 3},
        "sdc": {"min_cell": 10},
        "x": {"y": [1, 2]},
    }
    import typer

    with pytest.raises(typer.BadParameter):
        _parse_overrides(["novalue"])


def test_keygen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    r = runner.invoke(app, ["keygen", "--fernet"])
    assert r.exit_code == 0, r.stdout
    key = tmp_path / ".config" / "vamengoc" / "hmac.key"
    assert key.is_file() and oct(os.stat(key).st_mode)[-3:] == "600"
    assert len(bytes.fromhex(key.read_text().strip())) == 32
    before = key.read_text()
    r = runner.invoke(app, ["keygen"])
    assert "already exists" in r.stdout and key.read_text() == before


def test_schema_check(synthetic_dir: SyntheticDataset, tmp_path: Path) -> None:
    r = runner.invoke(app, ["schema-check", "--input", str(synthetic_dir.directory)])
    assert r.exit_code == 0, r.stdout
    assert "EA_2025_TOTAL.xlsx" in r.stdout and "9 AEFI files checked, 0 with problems." in r.stdout
    bad = tmp_path / "bad"
    bad.mkdir()
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["foo", "bar"])
    wb.save(bad / "EA_2019_TOTAL.xlsx")
    r = runner.invoke(app, ["schema-check", "--input", str(bad)])
    assert r.exit_code == 1


def test_synth_and_release_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "syn"
    r = runner.invoke(app, ["synth", "--out", str(out), "--scale", "0.01", "--seed", "5"])
    assert r.exit_code == 0 and (out / "SYNTHETIC_DATA.txt").is_file()
    r = runner.invoke(app, ["release", "verify", "does-not-exist"])
    assert r.exit_code == 2 and "FAILED" in r.stdout
