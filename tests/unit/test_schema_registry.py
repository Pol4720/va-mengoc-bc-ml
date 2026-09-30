"""Header detection and mapping."""

from __future__ import annotations

import pytest

from vamengoc.config import Project
from vamengoc.io.schema_registry import SchemaError, detect_header_row, fields_from_schema, match_headers
from vamengoc.synth.aefi_files import BASE_HEADER


@pytest.fixture(scope="module")
def fields() -> list:
    return fields_from_schema(Project().aefi_schema["fields"])


def test_base_header_maps_completely(fields: list) -> None:
    m = match_headers(BASE_HEADER, fields)
    assert not m.missing_required
    assert m.n_matched == len(BASE_HEADER) - 1  # the trailing blank column
    assert m.blank_columns == [len(BASE_HEADER) - 1]
    f2c = m.field_to_column()
    # repeated headers: personal history first, family history second
    assert f2c["hist_personal_seizure"] < f2c["hist_family_allergy"] < f2c["hist_family_seizure"]
    assert BASE_HEADER[f2c["manufacturer_raw"]] == "FABRICNATE"


def test_pandas_duplicate_suffix(fields: list) -> None:
    header = [h if h is not None else "" for h in BASE_HEADER]
    idx = [i for i, h in enumerate(header) if h == "ASMA"][1]
    header[idx] = "ASMA.1"
    m = match_headers(header, fields)
    assert header[m.field_to_column()["hist_family_asthma"]] == "ASMA.1"


def test_renamed_and_fuzzy_headers(fields: list) -> None:
    header = [h for h in BASE_HEADER if h is not None]
    header[header.index("FABRICNATE")] = "FABRICANTE"
    header[header.index("FIEBRE 39")] = "FIEBRE  39 "
    header[header.index("LLANTO PERSST.")] = "LLANTO PERSITENTE"  # typo -> fuzzy
    header.append("OBSERVACIONES")
    m = match_headers(header, fields)
    f2c = m.field_to_column()
    assert header[f2c["manufacturer_raw"]] == "FABRICANTE"
    assert header[f2c["ev_fever_39"]] == "FIEBRE  39 "
    assert any(f["field"] == "ev_persistent_crying" for f in m.fuzzy)
    assert {"column": len(header) - 1, "header": "OBSERVACIONES"} in m.unmatched
    report = m.as_report(header)
    assert report["n_matched"] == m.n_matched


def test_detect_header_below_title(fields: list) -> None:
    rows = [["REGISTRO 2020"], [], list(BASE_HEADER), ["x"] * len(BASE_HEADER)]
    idx, m = detect_header_row(rows, fields, max_rows=10, min_matches=5)
    assert idx == 2 and m.n_matched > 50


def test_no_header_raises(fields: list) -> None:
    with pytest.raises(SchemaError):
        detect_header_row([["a", "b"], ["c", "d"]], fields, max_rows=5, min_matches=5)


def test_missing_required_reported(fields: list) -> None:
    header = [h for h in BASE_HEADER if h not in (None, "F.VACUNACION")]
    m = match_headers(header, fields)
    assert "vaccination_date" in m.missing_required
