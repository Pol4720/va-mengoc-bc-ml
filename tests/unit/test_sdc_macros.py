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
    from vamengoc.release.sdc import SECONDARY_TOKEN

    # the single small cell in column A and row 1 forces complementary suppression; complementary
    # cells are not small counts, so they carry their own marker instead of "<5"
    assert out.loc[0, "A"] == "<5"
    supp = out[["A", "B"]].isin(["<5", SECONDARY_TOKEN])
    assert int(supp.to_numpy().sum()) >= 3
    assert int((out[["A", "B"]] == "<5").to_numpy().sum()) == 1
    for col in ("A", "B"):
        assert supp[col].sum() != 1
    for i in range(3):
        assert supp.loc[i].sum() != 1
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


def test_latex_text_and_bilingual(tmp_path: Path) -> None:
    from vamengoc.release.macros import join_words, latex_text, lower_first

    assert latex_text("Al(OH)₃ (log₁₀)") == "Al(OH)\\textsubscript{3} (log\\textsubscript{10})"
    assert latex_text("Fever ≥39 °C") == "Fever \\ensuremath{\\geq}39\\,°C"
    assert latex_text("T² – ok") == "T\\textsuperscript{2} -- ok"
    with pytest.raises(ValueError, match="no LaTeX mapping"):
        latex_text("emoji 🙂")
    assert lower_first("Fever") == "fever"
    assert lower_first("Al(OH)₃ concentration") == "Al(OH)₃ concentration"
    assert lower_first("IgG") == "IgG"
    assert lower_first("") == ""
    assert join_words([], "en") == "none" and join_words([], "es") == "ninguno"
    assert join_words(["a"], "en") == "a"
    assert join_words(["a", "b"], "en") == "a and b"
    assert join_words(["a", "b", "c"], "en") == "a, b, and c"
    assert join_words(["fiebre", "infección"], "es") == "fiebre e infección"
    assert join_words(["fiebre", "hielo"], "es") == "fiebre y hielo"
    m = MacroSet("PO")
    m.bilingual("Word", "increased", "aumentó")
    assert "\\newcommand{\\POWord}{\\VLang{increased}{aumentó}}" in m.render("x")


def test_pvalue_macros() -> None:
    from vamengoc.release.macros import format_p

    assert format_p(0.0004) == "\\ensuremath{<}\\num{0.001}"
    assert format_p(0.04213) == "\\num{0.042}"
    assert format_p(None) == format_p("x") == format_p(float("nan")) == "\\textemdash{}"
    assert format_p(1.2) == "\\num{1.000}"
    m = MacroSet("PO")
    m.pvalue("A", 0.0001)
    m.pvalue("B", 0.5)
    m.pvalue("C", None)
    text = m.render("x")
    assert "\\newcommand{\\POA}{\\ensuremath{{}<{}}\\num{0.001}}" in text
    assert "\\newcommand{\\POB}{\\ensuremath{{}={}}\\num{0.500}}" in text
    assert "\\newcommand{\\POC}{\\ensuremath{{}={}}\\textemdash{}}" in text


def test_long_secondary_and_implied_pct() -> None:
    from vamengoc.release.sdc import SECONDARY_TOKEN, suppress_implied_pct, suppress_long_secondary

    # Target cell 3 is small: with "All" and "Other" published it could be recovered by subtraction.
    df = pd.DataFrame(
        {
            "variable": ["v"] * 6,
            "level": ["a", "a", "a", "b", "b", "b"],
            "group": ["T", "O", "All"] * 2,
            "n": [3, 50, 53, 40, 60, 100],
            "pct": [7.0, 45.0, 34.6, 93.0, 55.0, 65.4],
        }
    )
    log = SDCLog()
    prim = suppress_counts(df, ["n"], min_cell=5, token="<5", derived={"n": ["pct"]}, table="t", log=log)
    out = suppress_long_secondary(
        prim,
        block_cols=["variable"],
        row_col="level",
        group_col="group",
        count_col="n",
        derived=["pct"],
        min_cell=5,
        token="<5",
        table="t",
        log=log,
    )
    sup = out["n"].isin(["<5", SECONDARY_TOKEN])
    # every level and every group with a suppressed cell has at least two
    for key in ("level", "group"):
        counts = out[sup].groupby(key).size()
        assert (counts >= 2).all()
    assert (out["n"] == "<5").sum() == 1 and (out["n"] == SECONDARY_TOKEN).sum() >= 2
    assert out.loc[sup, "pct"].isna().all()
    assert log.tables["t"]["secondary"] >= 2
    # implied counts: 2.4 % of 167 = 4 -> blanked; complement 99.4 % of 167 -> 1 -> blanked
    bias = pd.DataFrame({"n": [167, 167, 3000], "x_pct": [2.4, 99.4, 50.0]})
    res = suppress_implied_pct(bias, "n", ["x_pct", "missing_col"], min_cell=5, table="b", log=log)
    assert res["x_pct"].isna().tolist() == [True, True, False]
    assert log.tables["b"]["derived"] == 2


def test_builder_differencing_protections() -> None:
    from vamengoc.release.builder import (
        _protect_complement,
        _protect_cumulative,
        _protect_nested_designs,
        _protect_subset_events,
    )
    from vamengoc.release.sdc import SECONDARY_TOKEN, suppress_column_secondary

    dp = pd.DataFrame(
        {
            "design": ["primary_all_other_vaccines", "infant_active_comparator", "infant_active_comparator"],
            "event": ["e1", "e1", "e2"],
            "a": [20, 17, 9],
            "b": [100, 90, 50],
            "c": [30, 30, 10],
            "d": [500, 400, 300],
            "ror": [1.5, 1.4, 1.1],
        }
    )
    out = _protect_nested_designs(dp, 5, ["ror"])
    assert out.loc[1, "a"] == SECONDARY_TOKEN and out.loc[1, "ror"] is None  # 20 - 17 = 3 reports
    assert out.loc[2, "a"] == 9  # no primary row for e2
    cum = pd.DataFrame({"event": ["e"] * 3, "year": [2017, 2018, 2019], "a": [10, 12, 30], "ic": [0.1, 0.2, 0.3]})
    pc = _protect_cumulative(cum, 5, ["ic"])
    assert pc["a"].tolist() == [10, SECONDARY_TOKEN, 30] and pc.loc[1, "ic"] is None
    by_year = pd.DataFrame({"n_reports": [100, 100], "n_linked": [97, 80]})
    assert _protect_complement(by_year, "n_reports", "n_linked", 5)["n_linked"].tolist() == [SECONDARY_TOKEN, 80]
    prim = pd.DataFrame({"outcome": ["o"], "model": ["single"], "n_events": [50]})
    sens = pd.DataFrame({"outcome": ["o", "o"], "n_events": [48, 30]})
    assert _protect_subset_events(sens, prim, 5)["n_events"].tolist() == [SECONDARY_TOKEN, 30]
    assert _protect_subset_events(pd.DataFrame(), prim, 5).empty
    col = pd.DataFrame({"blk": ["x", "x", "x", "y"], "count": ["<5", 12, 40, 8], "rate": [None, 1.0, 2.0, 3.0]})
    cs = suppress_column_secondary(col, ["count", "nope"], token="<5", block_col="blk", derived={"count": ["rate"]})
    assert cs["count"].tolist() == ["<5", SECONDARY_TOKEN, 40, 8] and cs.loc[1, "rate"] is None
