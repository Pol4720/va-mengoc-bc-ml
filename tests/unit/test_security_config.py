"""Pseudonymisation keys, encryption and configuration."""

from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd
import pytest

from vamengoc.config import Project, deep_merge, find_project_root
from vamengoc.security import crypto
from vamengoc.security.pseudonymize import SYNTHETIC_TEST_KEY, Pseudonymizer, PseudonymKeyError, load_key


def test_key_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = str(tmp_path / "none.key")
    assert load_key("VAMENGOC_HMAC_KEY", missing, synthetic=True) == SYNTHETIC_TEST_KEY
    with pytest.raises(PseudonymKeyError, match="No pseudonymisation key"):
        load_key("VAMENGOC_HMAC_KEY", missing, synthetic=False)
    key = bytes(range(32))
    kf = tmp_path / "k.key"
    kf.write_text(key.hex(), encoding="utf-8")
    assert load_key("VAMENGOC_HMAC_KEY", str(kf), synthetic=False) == key
    monkeypatch.setenv("VAMENGOC_HMAC_KEY", base64.b64encode(bytes(range(1, 33))).decode())
    assert load_key("VAMENGOC_HMAC_KEY", missing, synthetic=False) == bytes(range(1, 33))
    monkeypatch.setenv("VAMENGOC_HMAC_KEY", SYNTHETIC_TEST_KEY.hex())
    with pytest.raises(PseudonymKeyError, match="must not be used on real data"):
        load_key("VAMENGOC_HMAC_KEY", missing, synthetic=False)
    monkeypatch.setenv("VAMENGOC_HMAC_KEY", "abcd")
    with pytest.raises(PseudonymKeyError):
        load_key("VAMENGOC_HMAC_KEY", missing, synthetic=False)


def test_pseudonymizer_is_stable_and_keyed() -> None:
    p = Pseudonymizer(SYNTHETIC_TEST_KEY)
    a = p.person_id("Ana  Pérez ", "2017-01-01", "F")
    assert a == p.person_id("ANA PEREZ", "2017-01-01", "F")  # normalised
    assert a != p.person_id("Ana Pérez", "2017-01-02", "F")
    other = Pseudonymizer(bytes(range(32)))
    assert other.person_id("Ana Pérez", "2017-01-01", "F") != a
    assert a.startswith("P") and len(a) == 21
    assert p.record_id("abc", 3) != p.record_id("abc", 4)
    assert p.generic("clinic", "12").startswith("C")
    with pytest.raises(PseudonymKeyError):
        Pseudonymizer(b"short")


def test_crypto_roundtrip(tmp_path: Path) -> None:
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    plain = crypto.write_parquet(df, tmp_path / "t", None)
    assert plain.suffix == ".parquet"
    pd.testing.assert_frame_equal(crypto.read_parquet(tmp_path / "t", None), df)
    key_file = tmp_path / "f.key"
    key_file.write_text(crypto.generate_key().decode(), encoding="utf-8")
    fernet = crypto.load_fernet("NOPE_ENV", str(key_file))
    enc = crypto.write_parquet(df, tmp_path / "e", fernet)
    assert enc.name.endswith(".parquet.enc")
    assert b"PAR1" not in enc.read_bytes()[:8]
    pd.testing.assert_frame_equal(crypto.read_parquet(tmp_path / "e", fernet), df)
    with pytest.raises(RuntimeError):
        crypto.read_parquet(tmp_path / "e", None)
    with pytest.raises(RuntimeError):
        crypto.load_fernet("NOPE_ENV", str(tmp_path / "missing"))


def test_config_and_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pr = Project(overrides={"analysis": {"seed": 7}, "sdc": {"min_cell": 11}})
    assert pr.config.analysis.seed == 7 and pr.config.sdc.min_cell == 11
    assert pr.config.analysis.target_vaccine == "AM-BC"
    fp = pr.config_fingerprint()
    assert "configs/pipeline.yaml" in fp and "<merged pipeline config>" in fp
    assert fp["<merged pipeline config>"] != Project().config_fingerprint()["<merged pipeline config>"]
    assert pr.path("/abs/x") == Path("/abs/x")
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {"a": {"b": 3, "c": 2}}
    with pytest.raises(ValueError, match="study_years"):
        Project(overrides={"analysis": {"study_years": [2025, 2017]}})
    monkeypatch.setenv("VAMENGOC_HOME", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        find_project_root()
    monkeypatch.delenv("VAMENGOC_HOME")
    assert (find_project_root(tmp_path) / "configs" / "pipeline.yaml").is_file()
