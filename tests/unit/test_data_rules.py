"""Rules for the known data problems: mistyped years, schedule ages, lot validity, comparator,
partial years and sheet selection (synthetic values only)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from vamengoc.config import Project
from vamengoc.curate.lot_validity import (
    check_code_rules,
    code_digits,
    lot_status,
    release_year_from_code,
)
from vamengoc.curate.rules import (
    SCHEDULE_EXCLUDED,
    apply_comparator,
    comparator_products,
    month_coverage,
    resolve_last_year,
    schedule_status,
)
from vamengoc.io.schema_registry import fields_from_schema
from vamengoc.parsing.dates import repair_report_dates

D = dt.date


# --- mistyped years ------------------------------------------------------------------------
def test_vaccination_year_typo_is_corrected_from_notification() -> None:
    v, n, rv, rn = repair_report_dates(D(2029, 3, 10), D(2019, 3, 12), 2019)
    assert (v, n, rv, rn) == (D(2019, 3, 10), D(2019, 3, 12), "imputed_year", "kept")


def test_notification_year_typo_is_corrected_from_vaccination() -> None:
    _, n, rv, rn = repair_report_dates(D(2019, 5, 2), D(2002, 5, 6), 2019)
    assert n == D(2019, 5, 6) and rn == "imputed_year" and rv == "kept"


def test_correction_needs_a_coherent_delay() -> None:
    # Day and month kept: December 2019 would follow the January notification, so 2018 is used.
    v, _, rv, _ = repair_report_dates(D(2029, 12, 20), D(2019, 1, 5), 2019)
    assert v == D(2018, 12, 20) and rv == "imputed_year"  # previous year gives a 16-day delay
    v, _, rv, _ = repair_report_dates(D(2075, 6, 1), D(2019, 1, 5), 2019, max_delay_days=30)
    assert v is None and rv == "dropped_impossible"


def test_previous_year_vaccinations_are_kept() -> None:
    v, _, rv, rn = repair_report_dates(D(2023, 12, 28), D(2024, 1, 3), 2024)
    assert (rv, rn) == ("kept", "kept") and v == D(2023, 12, 28)


def test_consistent_old_dates_are_kept() -> None:
    v, n, rv, rn = repair_report_dates(D(2016, 3, 1), D(2016, 3, 9), 2019)
    assert (v, n) == (D(2016, 3, 1), D(2016, 3, 9)) and rv == rn == "kept_consistent"


def test_vaccination_after_the_workbook_year_kept_when_coherent() -> None:
    v, _, rv, _ = repair_report_dates(D(2018, 1, 3), D(2018, 1, 9), 2017)
    assert v == D(2018, 1, 3) and rv == "kept_consistent"


def test_without_reference_the_workbook_year_is_used() -> None:
    v, n, rv, _ = repair_report_dates(D(2091, 4, 4), None, 2019)
    assert v == D(2019, 4, 4) and rv == "imputed_year" and n is None


# --- schedule ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def project() -> Project:
    return Project()


@pytest.mark.parametrize(
    ("age", "exact", "dose", "expected"),
    [
        (3.1, True, "1", "on_schedule"),
        (2.0, True, "1", "too_young"),
        (2.0, False, "1", "early"),  # "2M" may be 2 months 29 days: not provably too young
        (1.0, False, "1", "too_young"),
        (2.9, True, "1", "early"),
        (4.0, True, "2", "too_young"),  # below 3 months + 6 weeks
        (4.6, True, "2", "early"),
        (5.2, True, "2", "on_schedule"),
        (30.0, True, "1", "late"),  # catch-up dose
        (5.0, True, "3", "dose_not_in_schedule"),
        (14.0, True, "R", "booster_campaign"),
        (None, True, "1", "unknown_age"),
        (3.0, True, None, "unknown_dose"),
    ],
)
def test_schedule_status(project: Project, age: float | None, exact: bool, dose: str | None, expected: str) -> None:
    assert schedule_status(age, exact, dose, project.config.analysis) == expected


def test_only_impossible_administrations_are_excluded() -> None:
    assert {"too_young", "dose_not_in_schedule", "above_indication"} == set(SCHEDULE_EXCLUDED)


# --- lot validity --------------------------------------------------------------------------
def test_first_digit_is_the_release_year() -> None:
    assert code_digits("812M", "digits_first1") == 8
    assert code_digits("M412", "digits_first1") == 4
    assert release_year_from_code("812M", 2019) == 2018
    assert release_year_from_code("101M", 2012) == 2011  # same digit as 2001 and 2021
    assert release_year_from_code("101M", 2022) == 2021


@pytest.mark.parametrize(
    ("lot", "year", "status"),
    [("812M", 2018, "valid"), ("812M", 2021, "valid"), ("812M", 2022, "expired"), ("512M", 2019, "expired")],
)
def test_lot_status_from_code(lot: str, year: int, status: str) -> None:
    assert lot_status(release_year_from_code(lot, year), year, 3) == status


def test_before_release_and_unassessable() -> None:
    assert lot_status(2020, 2019, 3) == "before_release"
    assert lot_status(None, 2019, 3) == "not_assessable"


def test_code_rule_is_checked_against_the_workbook() -> None:
    lots = pd.DataFrame({"lot_exact": ["812M", "915M", "M311", "101X"], "production_year": [2018, 2018, 2013, 2011]})
    checks = {c.rule: c for c in check_code_rules(lots, ["digits_first1", "digits_last1"], 0.7)}
    assert checks["digits_first1"].accepted  # 915M released the year after production
    assert checks["digits_first1"].agreement_exact == pytest.approx(0.75)
    assert checks["digits_first1"].agreement_within1 == pytest.approx(1.0)
    assert not checks["digits_last1"].accepted


# --- comparator ----------------------------------------------------------------------------
def test_comparator_products_are_finlay_only(project: Project) -> None:
    prods = comparator_products(project)
    assert "AM-BC" not in prods
    assert {"DPT", "TT", "SOBERANA", "PCV7-TT"} <= set(prods)
    assert not {"PENTA-L", "PCV", "ABDALA", "PRS"} & set(prods)


def test_apply_comparator() -> None:
    df = pd.DataFrame(
        {"vaccines": ["AM-BC", "DPT", "PENTA-L", "DPT|PENTA-L", None], "has_target": [True, False, False, False, False]}
    )
    out = apply_comparator(df, ["DPT", "TT"])
    assert out["finlay_comparator"].tolist() == [False, True, False, True, False]
    assert out["concomitant_non_comparator"].tolist() == [False, False, False, True, False]


# --- partial years -------------------------------------------------------------------------
def test_month_coverage_ignores_stray_months() -> None:
    rows = []
    for m in range(1, 8):  # a workbook with January-July
        rows += [{"file_year": 2023, "month_reported": m, "notification_date": pd.NaT}] * 40
    rows += [{"file_year": 2023, "month_reported": 11, "notification_date": pd.NaT}]  # one mistyped month
    df = pd.DataFrame(rows)
    df["notification_date"] = pd.to_datetime(df["notification_date"])
    cov = month_coverage(df)
    assert int(cov["observed"].sum()) == 7
    assert cov.set_index("month").loc[11, "n_reports"] == 1


def test_open_ended_window_follows_the_data() -> None:
    assert resolve_last_year(None, pd.Series([2017, 2026])) == 2026
    assert resolve_last_year(2025, pd.Series([2017, 2026])) == 2025


# --- sheet selection -----------------------------------------------------------------------
def _sheet(wb: Workbook, name: str, header: list[str], n: int) -> None:
    ws = wb.create_sheet(name)
    ws.append(header)
    for i in range(n):
        ws.append([f"x{i}", "M", "2M", "01/02/2021", "02/02/2021", "AM-BC", "1", "101M", "N"])


def test_master_sheet_preferred_and_product_extracts_skipped(tmp_path: Path, project: Project) -> None:
    from vamengoc.ingest.aefi import _choose_sheets

    header = [
        "NOMBRES Y APELLIDOS",
        "SEXO",
        "EDAD",
        "F.VACUNACION",
        "F.NOTIFICACION",
        "TIPO DE VACUNA",
        "DOSIS",
        "LOTE",
        "FIEBRE 39",
    ]
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "ABDALA", header, 50)  # alphabetically first, bigger: must be skipped
    _sheet(wb, "Eventos Adversos Total", header, 10)
    _sheet(wb, "Casos que no entraronen el cier", header, 3)
    path = tmp_path / "EA 2021 TOTAL.xlsx"
    wb.save(path)
    fields = fields_from_schema(project.aefi_schema["fields"])
    chosen = _choose_sheets(path, "TOTAL", fields, project)
    assert [(g.sheet, role) for g, _, _, role in chosen] == [
        ("Eventos Adversos Total", "master"),
        ("Casos que no entraronen el cier", "extra"),
    ]


# --- Paper 2 feasibility -------------------------------------------------------------------
def _feasibility(project: Project, n_valid: int, n_bad: int, n_lots: int) -> dict[str, object]:
    from vamengoc.curate.linkage import LinkageResult
    from vamengoc.pipeline import p2_feasibility

    n = n_valid + n_bad
    links = pd.DataFrame(
        {
            "record_id": [f"r{i}" for i in range(n)],
            "lot_key": [f"L{i % n_lots}" for i in range(n)],
            "lot_status": ["valid"] * n_valid + ["expired"] * n_bad,
        }
    )
    window = pd.DataFrame({"record_id": links["record_id"], "schedule_invalid": False})
    return p2_feasibility(LinkageResult(links=links), window, project.config.analysis.p2_feasibility)


@pytest.mark.parametrize(
    ("n_valid", "n_bad", "n_lots", "verdict"),
    [
        (950, 50, 60, "adequate"),
        (850, 150, 60, "limited"),
        (700, 300, 60, "insufficient"),
        (150, 0, 60, "insufficient"),
    ],
)
def test_p2_feasibility_rule(project: Project, n_valid: int, n_bad: int, n_lots: int, verdict: str) -> None:
    fz = _feasibility(project, n_valid, n_bad, n_lots)
    assert fz["verdict"] == verdict
    if verdict == "insufficient" and n_bad:
        assert "inconsistent_share" in fz["reasons"]


def test_feasibility_wording_is_generated(project: Project) -> None:
    from vamengoc.release.builder import _feasibility_words
    from vamengoc.release.macros import MacroSet

    for n_bad, word in ((50, "supported"), (300, "not supported")):
        m = MacroSet("PT")
        _feasibility_words(m, _feasibility(project, 1000 - n_bad, n_bad, 60))
        assert word in m.items["PTFeasibilityWord"]
        assert "PTFeasibilitySentence" in m.items and "PTConclusionSentence" in m.items
