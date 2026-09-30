"""Disclosure control and macro generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from vamengoc.release.macros import MacroSet, macro_name
from vamengoc.release.sdc import SDCLog, suppress_counts, suppress_linked, suppress_wide_secondary


def test_primary_and_derived_suppression() -> None:
    log = SDCLog()
    df = pd.DataFrame({"n": [0, 1, 4, 5, 120], "pct": [0.0, 0.1, 0.4, 0.5, 12.0], "label": list("abcde")})
    out = suppress_counts(df, ["n", "missing_col"], min_cell=5, token="<5", derived={"n": ["pct"]}, table="t", log=log)
    assert list(out["n"]) == [0, "<5", "<5", 5, 120]
    assert out["pct"].isna().tolist() == [False, True, True, False, False]
    assert log.tables["t"] == {"primary": 2, "derived": 2, "secondary": 0}
    assert log.total()["primary"] == 2


def test_linked_suppression() -> None:
    df = pd.DataFrame({"a": [2, 50], "ror": [3.0, 1.2], "ic": [0.5, 0.1]})
    out = suppress_linked(df, "a", ["ror", "ic", "absent"], min_cell=5)
    assert pd.isna(out.loc[0, "ror"]) and out.loc[1, "ror"] == 1.2


def test_secondary_suppression_protects_margins() -> None:
    wide = pd.DataFrame({"cls": [1, 2, 3], "A": [3, 40, 50], "B": [60, 30, 20]})
    log = SDCLog()
    out = suppress_wide_secondary(wide, ["A", "B"], min_cell=5, token="<5", table="w", log=log)
    # the single small cell in column A and row 1 forces complementary suppression
    assert out.loc[0, "A"] == "<5"
    n_supp = (out[["A", "B"]] == "<5").sum().sum()
    assert n_supp >= 3
    for col in ("A", "B"):
        assert (out[col] == "<5").sum() != 1
    for i in range(3):
        assert (out.loc[i, ["A", "B"]] == "<5").sum() != 1
    assert log.tables["w"]["secondary"] >= 2


def test_macro_names_and_rendering(tmp_path: Path) -> None:
    assert macro_name("PO", "ev_fever_39 ROR") == "POEvFeverThreeNineROR"
    m = MacroSet("PT", suppression_token="<5")
    m.number("NLots", 736)
    m.number("Rate", 30.678, 1)
    m.number("Small", "<5")
    m.number("Missing", None)
    m.number("NaN", float("nan"))
    m.number("Inf", float("inf"))
    m.number("Text", "abc_1")
    m.number("NumStr", "12.5", 1)
    m.percent("Pct", 12.34)
    m.percent("PctMissing", None)
    m.interval("CI", 1.0, 2.0, 2)
    m.interval("CINone", None, None)
    m.text("Label", "50% & more_x")
    with pytest.raises(ValueError, match="duplicate"):
        m.number("NLots", 1)
    text = m.render("test")
    assert "\\newcommand{\\PTNLots}{\\num{736}}" in text
    assert "\\newcommand{\\PTRate}{\\num{30.7}}" in text
    assert "\\newcommand{\\PTSmall}{\\ensuremath{<}\\num{5}}" in text
    assert "\\newcommand{\\PTPct}{\\qty{12.3}{\\percent}}" in text
    assert "\\newcommand{\\PTCINone}{\\textemdash{}}" in text
    assert "\\newcommand{\\PTLabel}{50\\% \\& more\\_x}" in text
    assert "\\PTInf}{\\ensuremath{\\infty}}" in text
    path = m.write(tmp_path / "m.tex", "hdr")
    assert path.read_text(encoding="utf-8").startswith("% hdr")
