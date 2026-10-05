"""Changes of source layout: the AEFI form used from 2024 and renamed lot-release columns."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from vamengoc.analysis import disproportionality as dp
from vamengoc.config import Project
from vamengoc.curate.aefi_model import events_recorded_everywhere, recorded_mask
from vamengoc.io.schema_registry import FieldSpec, fields_from_schema, match_headers
from vamengoc.synth.aefi_files import BASE_HEADER

# Headers of the 2024-2025 files as reported by `vamengoc schema-check` on the real data
# (column titles only), on top of the columns shared with the earlier form.
NEW_FORM_COLUMNS = [
    "CARNE DE IDENTIDAD",
    "APP CONVULSON",
    "APP ASMA",
    "APP HTA",
    "APP DM",
    "APP CI",
    "DOLOR",
    "ENROJECIMIENTO",
    "INDURACION",
    "ABSCESO",
    "SOMNOLENCIA",
    "TA ALTA",
    "DECAIMIENTO",
    "CEFALEA",
    "CRISS VAGAL",
    "ERITEMA",
    "ANAFILAXIA",
    "FEBRICULA",
    "FIEBRE",
    "TROMBOCITOPENIA",
    "EDEMA LABIAL",
    "EDEMA FACIAL",
    "PARALISS FACIAL",
    "GRAVE",
    "NO GRAVE",
]


@pytest.fixture(scope="module")
def aefi_fields() -> list[FieldSpec]:
    return fields_from_schema(Project().aefi_schema["fields"])


@pytest.fixture(scope="module")
def lot_fields() -> list[FieldSpec]:
    return fields_from_schema(Project().lots_schema["lots_sheet"]["fields"])


def test_new_form_columns_are_all_recognised(aefi_fields: list[FieldSpec]) -> None:
    shared = ["SEXO", "EDAD", "PROVINCIAS", "F.VACUNACION", "F.NTIFICACION", "TIPO DE VACUNA", "LOTE"]
    m = match_headers(shared + NEW_FORM_COLUMNS, aefi_fields)
    assert not m.unmatched, m.unmatched
    f2c = m.field_to_column()
    # the misspelt notification-date header is an alias now, not a fuzzy guess
    assert "notification_date" in f2c and not m.fuzzy
    for name in ("national_id", "ev_vasovagal", "ev_facial_palsy", "ev_fever_unspecified", "reported_serious"):
        assert name in f2c
    assert f2c["hist_personal_seizure"] == shared.__len__() + NEW_FORM_COLUMNS.index("APP CONVULSON")
    # "FIEBRE" alone is not mistaken for the thresholded indicators of the earlier form
    assert "ev_fever_39" not in f2c and "ev_fever_40" not in f2c
    assert "reported_non_serious" in f2c


def test_earlier_form_is_unchanged(aefi_fields: list[FieldSpec]) -> None:
    m = match_headers(BASE_HEADER, aefi_fields)
    assert m.n_matched == len(BASE_HEADER) - 1
    assert not {"ev_fever_unspecified", "ev_abscess_unspecified", "national_id"} & set(m.field_to_column())


def test_every_event_indicator_has_labels() -> None:
    p = Project()
    catalogue = p.events["events"]
    for name in p.aefi_schema["fields"]:
        if name.startswith("ev_"):
            assert {"label_en", "label_es", "domain", "class", "expected"} <= set(catalogue[name]), name


def test_lot_attribute_found_by_pattern(lot_fields: list[FieldSpec]) -> None:
    header = ["LOTE", "AÑO", "PH", "Inmunogenicidad (act. antic. bact.)", "Anticuerpos IgG por ELISA (UIgG/mL)"]
    m = match_headers(header, lot_fields)
    f2c = m.field_to_column()
    assert f2c["igg_elisa"] == 4 and f2c["bactericidal_titer"] == 3
    assert m.fuzzy == [{"column": 4, "header": header[4], "field": "igg_elisa", "score": "pattern"}]


def test_ambiguous_pattern_is_left_for_review() -> None:
    fields = [
        FieldSpec("a", ("ALPHA",), patterns=("PROT",)),
        FieldSpec("b", ("BETA",), patterns=("PROT",)),
    ]
    m = match_headers(["PROTEINA X"], fields)
    assert not m.columns and m.unmatched[0]["header"] == "PROTEINA X"


def test_quality_attributes_are_optional(lot_fields: list[FieldSpec]) -> None:
    required = {f.name for f in lot_fields if f.required}
    assert required == {"lot_id", "production_year"}


# --- analyses restricted to the files whose form recorded the event ---------------------------
def _reports() -> tuple[pd.DataFrame, dict[str, list[str]]]:
    rep = pd.DataFrame(
        {
            "source_file": ["old.xlsx"] * 4 + ["new.xlsx"] * 4,
            "ev_fever_39": pd.array([True, True, False, False, None, None, None, None], dtype="boolean"),
            "ev_pain": pd.array([None] * 4 + [True, False, True, False], dtype="boolean"),
            "hospitalized": pd.array([False] * 8, dtype="boolean"),
        }
    )
    recorded = {"old.xlsx": ["ev_fever_39"], "new.xlsx": ["ev_pain"]}
    return rep, recorded


def test_recorded_mask_and_events_everywhere() -> None:
    rep, recorded = _reports()
    assert recorded_mask(rep, "ev_fever_39", recorded).tolist() == [True] * 4 + [False] * 4
    assert recorded_mask(rep, "ev_pain", recorded).tolist() == [False] * 4 + [True] * 4
    # outcomes are on every form; without file information everything counts
    assert recorded_mask(rep, "hospitalized", recorded).all()
    assert recorded_mask(rep, "ev_fever_39", {}).all()
    assert events_recorded_everywhere(rep, ["ev_fever_39", "ev_pain"], recorded) == []
    assert events_recorded_everywhere(rep[rep["source_file"] == "old.xlsx"], ["ev_fever_39"], recorded) == [
        "ev_fever_39"
    ]


def test_disproportionality_uses_only_recorded_reports() -> None:
    rep, recorded = _reports()
    target = pd.Series([True, False, True, False, True, False, True, False])
    known = {e: recorded_mask(rep, e, recorded) for e in ("ev_fever_39", "ev_pain")}
    tab = dp.disproportionality_table(rep, target, ~target, ["ev_fever_39", "ev_pain"], recorded=known)
    fever = tab.set_index("event").loc["ev_fever_39"]
    # the four reports of the new form, where fever >=39 was not on the form, are not counted as "no fever"
    assert (fever["a"], fever["b"], fever["c"], fever["d"]) == (1, 1, 1, 1)
    unrestricted = dp.disproportionality_table(rep, target, ~target, ["ev_fever_39"]).iloc[0]
    assert unrestricted["b"] == 3


def test_vaccine_event_counts_restriction_is_neutral_when_everything_is_recorded() -> None:
    adm = pd.DataFrame({"record_id": [1, 2, 3, 4, 4], "vaccine": ["A", "B", "A", "B", "A"]})
    events_long = pd.DataFrame(
        {"record_id": [1, 2, 3, 4], "event": ["e1", "e1", "e2", "e2"], "present": [True, False, True, True]}
    )
    ids = pd.Series([1, 2, 3, 4])
    plain = dp.vaccine_event_counts(adm, events_long, ids)
    restricted = dp.vaccine_event_counts(adm, events_long, ids, recorded={"e1": {1, 2, 3, 4}, "e2": {1, 2, 3, 4}})
    key = ["vaccine", "event"]
    pd.testing.assert_frame_equal(
        plain.sort_values(key).reset_index(drop=True),
        restricted.sort_values(key).reset_index(drop=True),
        check_dtype=False,
    )
    only_new = dp.vaccine_event_counts(adm, events_long, ids, recorded={"e1": {1, 2}, "e2": {3, 4}})
    e2 = only_new[only_new["event"] == "e2"].set_index("vaccine")
    assert e2.loc["A", "n"] == 2 and e2.loc["A", "expected"] == pytest.approx(2 * 2 / 2)


def test_released_schema_drift_never_uses_identifier_names_as_keys() -> None:
    from vamengoc.release.builder import forbidden_columns, public_schema_drift
    from vamengoc.release.verify import VerificationReport, _walk_json

    drift = {
        "fields_in_all_files": ["sex", "birth_date", "vaccine_raw"],
        "fields_not_in_all_files": {"birth_date": ["EA 2024.xlsx"], "national_id": ["EA 2017.xlsx"], "ev_pain": []},
        "unmatched_headers": {},
        "fuzzy_matches": {},
    }
    forbidden = forbidden_columns(Project().config.sdc.forbidden_columns)
    assert {"birth_date", "national_id"} <= forbidden
    out = public_schema_drift(drift, forbidden)
    assert out["fields_not_in_all_files"] == {"ev_pain": []}
    assert out["identifier_fields_not_in_all_files"] == 2
    assert out["fields_in_all_files"] == ["sex", "vaccine_raw"]
    rep = VerificationReport(root=Path())
    _walk_json({"schema_drift": out}, "$", forbidden, rep, "dq_summary.json")
    assert rep.ok, rep.errors
