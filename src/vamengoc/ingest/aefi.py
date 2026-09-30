"""Ingestion of the annual AEFI workbooks into a typed, pseudonymised staging table.

Direct identifiers are consumed in memory (to derive the HMAC person key and
the exact-duplicate digest) and never stored. The output keeps, for each
report, typed values plus parse-status columns for the fields whose repair
rules matter to sensitivity analyses.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from vamengoc.config import Project
from vamengoc.io.excel import SheetGrid, list_sheets, read_sheet
from vamengoc.io.schema_registry import (
    FieldSpec,
    HeaderMatch,
    SchemaError,
    detect_header_row,
    fields_from_schema,
)
from vamengoc.normalize.registry import Normalizers
from vamengoc.parsing.ages import (
    age_group_from_months,
    normalize_age_group,
    parse_age,
    reconcile_age,
)
from vamengoc.parsing.dates import parse_date
from vamengoc.parsing.doses import parse_dose
from vamengoc.parsing.lots import parse_lots
from vamengoc.parsing.text import cell_to_str, normalize_text, strip_accents
from vamengoc.parsing.values import Status, parse_integer, parse_sex, parse_yes_no
from vamengoc.provenance import RunContext
from vamengoc.security.pseudonymize import Pseudonymizer

__all__ = ["AEFIIngestResult", "discover_aefi_files", "ingest_aefi"]


@dataclass
class AEFIIngestResult:
    staging: pd.DataFrame
    schema_reports: dict[str, dict[str, Any]]
    parse_status: dict[str, dict[str, dict[str, int]]]  # file -> field -> status -> n
    local_only: dict[str, Any] = field(default_factory=dict)  # never released


def discover_aefi_files(directory: Path, pattern: str) -> list[tuple[int, Path]]:
    """Return ``(file_year, path)`` for every AEFI workbook, sorted by year then name."""
    rx = re.compile(pattern)
    found = []
    for p in sorted(directory.iterdir()) if directory.is_dir() else []:
        if not p.is_file() or p.name.startswith(("~$", ".")):
            continue
        m = rx.match(p.name)
        if m:
            found.append((int(m.group("year")), p))
    return sorted(found, key=lambda t: (t[0], t[1].name))


def _choose_sheet(
    path: Path, preferred: str, fields: list[FieldSpec], project: Project
) -> tuple[SheetGrid, int, HeaderMatch]:
    inputs = project.config.inputs
    names = list_sheets(path)
    ordered = sorted(names, key=lambda n: (normalize_text(n) != normalize_text(preferred), n))
    last_error: Exception | None = None
    for name in ordered:
        grid = read_sheet(path, name)
        try:
            idx, match = detect_header_row(
                grid.rows, fields, max_rows=inputs.header_search_rows, min_matches=inputs.min_header_matches
            )
        except SchemaError as exc:
            last_error = exc
            continue
        return grid, idx, match
    msg = f"{path.name}: no sheet matches the AEFI schema ({last_error})"
    raise SchemaError(msg)


def _row_digest(key: bytes, cells: list[Any]) -> str:
    """Keyed digest of a full raw row (exact-duplicate detection without storing values)."""
    payload = "\x1f".join(cell_to_str(c) or "" for c in cells).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()[:24]


def _categorise_other(text: Any, patterns: dict[str, list[str]]) -> list[str]:
    """Keyword categories of the free-text 'other' field (text itself is discarded)."""
    s = strip_accents(cell_to_str(text) or "").upper()
    if normalize_text(s) in {"", "N", "NO", "NINGUNO", "NINGUNA"}:
        return []
    cats = [cat for cat, pats in patterns.items() if any(p in s for p in pats)]
    return cats or ["uncategorised"]


def _join(values: list[str] | tuple[str, ...] | None) -> str | None:
    if not values:
        return None
    return "|".join(values)


_EVENT_TYPES = {"yes_no"}


def ingest_aefi(
    project: Project,
    directory: Path,
    norm: Normalizers,
    pseudo: Pseudonymizer,
    ctx: RunContext,
) -> AEFIIngestResult:
    """Read every AEFI workbook in ``directory`` into one staging DataFrame."""
    schema = project.aefi_schema
    fields = fields_from_schema(schema["fields"])
    spec_by_name = {f.name: f for f in fields}
    files = discover_aefi_files(directory, project.config.inputs.aefi_file_pattern)
    if not files:
        msg = f"No AEFI files matching {project.config.inputs.aefi_file_pattern!r} in {directory}"
        raise FileNotFoundError(msg)

    plaus = project.config.analysis.plausibility
    digest_key = hashlib.sha256(pseudo.token("row-digest-key").encode()).digest()
    records: list[dict[str, Any]] = []
    schema_reports: dict[str, dict[str, Any]] = {}
    parse_status: dict[str, dict[str, dict[str, int]]] = {}
    unmapped_vaccines: Counter[str] = Counter()
    other_uncategorised: Counter[str] = Counter()

    for file_year, path in files:
        sha = ctx.register_input(path)
        grid, header_idx, match = _choose_sheet(path, project.config.inputs.aefi_preferred_sheet, fields, project)
        headers = grid.rows[header_idx]
        report = match.as_report(headers)
        report.update({"sheet": grid.sheet, "header_row": header_idx + 1, "file_year": file_year})
        if match.missing_required:
            msg = f"{path.name}: required AEFI fields missing: {match.missing_required}"
            raise SchemaError(msg)

        col_of = match.field_to_column()
        junk_cols = [c for c in range(len(headers)) if c not in match.columns]
        junk_nonnull: Counter[int] = Counter()
        status: dict[str, Counter[str]] = defaultdict(Counter)
        n_rows = 0

        for r in range(header_idx + 1, grid.n_rows):
            row = grid.rows[r]
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
                continue
            n_rows += 1
            for c in junk_cols:
                if c < len(row) and row[c] is not None and str(row[c]).strip():
                    junk_nonnull[c] += 1

            def raw(name: str, _row: list[Any] = row, _col_of: dict[str, int] = col_of) -> Any:
                c = _col_of.get(name)
                return _row[c] if c is not None and c < len(_row) else None

            rec: dict[str, Any] = {
                "record_id": pseudo.record_id(sha, r + 1),
                "source_file": path.name,
                "file_year": file_year,
                "source_row": r + 1,
                "row_digest": _row_digest(digest_key, [row[c] for c in sorted(match.columns)]),
            }

            # --- demography -------------------------------------------------------
            sex = parse_sex(raw("sex"))
            status["sex"][sex.status] += 1
            rec["sex"] = sex.value
            bdate = parse_date(raw("birth_date"))
            status["birth_date"][bdate.status] += 1
            vdate = parse_date(raw("vaccination_date"))
            status["vaccination_date"][vdate.status] += 1
            ndate = parse_date(raw("notification_date"))
            status["notification_date"][ndate.status] += 1
            rec["vaccination_date"] = vdate.value
            rec["notification_date"] = ndate.value
            rec["vaccination_date_status"] = vdate.status
            rec["notification_date_status"] = ndate.status

            # Pseudonymous person key: name + birth date + sex, consumed here only.
            name_present = normalize_text(raw("full_name")) != ""
            strong = name_present and bdate.value is not None
            # Without name AND birth date the key could merge different people:
            # weak keys are made record-specific so they never link reports.
            rec["person_id"] = (
                pseudo.person_id(raw("full_name"), bdate.value, sex.value)
                if strong
                else "W" + pseudo.token("weak", sha, r + 1)
            )
            rec["person_id_strength"] = "strong" if strong else "weak"

            age = parse_age(raw("age_raw"))
            status["age_raw"][age.status] += 1
            rec_age = reconcile_age(
                age.value,
                bdate.value,
                vdate.value,
                tolerance_months=plaus.age_tolerance_months,
                max_age_years=plaus.max_age_years,
            )
            rec["age_reported_months"] = age.value
            rec["age_months"] = rec_age.months
            rec["age_source"] = rec_age.source
            rec["age_discrepancy_months"] = rec_age.discrepancy_months
            rec["age_group_reported"] = normalize_age_group(raw("age_group_raw"))
            rec["age_group"] = age_group_from_months(rec_age.months)
            rec["birth_year"] = bdate.value.year if bdate.value else None
            rec["birth_after_vaccination"] = bool(bdate.value and vdate.value and bdate.value > vdate.value)

            prov_raw = raw("province")
            prov = norm.province.map(prov_raw)
            status["province"][
                Status.OK if prov else (Status.MISSING if normalize_text(prov_raw) == "" else Status.INVALID)
            ] += 1
            rec["province"] = prov
            rec["region"] = norm.province_region.get(prov) if prov else None
            rec["municipality_norm"] = normalize_text(raw("municipality")) or None
            rec["health_area_norm"] = normalize_text(raw("health_area")) or None
            clinic = normalize_text(raw("clinic"))
            rec["clinic_pseudo"] = pseudo.generic("clinic", f"{prov}|{clinic}") if clinic else None
            preg = parse_yes_no(raw("pregnant"))
            status["pregnant"][preg.status] += 1
            rec["pregnant"] = preg.value
            month = parse_integer(raw("month"))
            rec["month_reported"] = month.value if month.value and 1 <= month.value <= 12 else None

            # --- vaccination --------------------------------------------------------
            vac_codes, vac_unmapped = norm.vaccines(raw("vaccine_raw"))
            for tok in vac_unmapped:
                unmapped_vaccines[tok] += 1
            status["vaccine_raw"][
                Status.OK if vac_codes and not vac_unmapped else (Status.MISSING if not vac_codes else Status.INVALID)
            ] += 1
            rec["vaccines"] = _join(vac_codes)
            dose = parse_dose(raw("dose_raw"))
            status["dose_raw"][dose.status] += 1
            rec["doses"] = _join(dose.value)
            rec["dose_status"] = dose.status
            rec["sites"] = _join(norm.sites(raw("site_raw")))
            rec["routes"] = _join(norm.routes(raw("route_raw")))
            place_raw = raw("place_raw")
            rec["place"] = norm.place.map(place_raw) if normalize_text(place_raw) else None
            rec["manufacturers"] = _join(norm.manufacturers(raw("manufacturer_raw")))
            lots = parse_lots(raw("lot_raw"))
            status["lot_raw"][lots.status] += 1
            rec["lots_exact"] = _join([k.exact for k in lots.value] if lots.value else None)
            rec["lots_core"] = _join([k.core or "" for k in lots.value] if lots.value else None)
            rec["lot_status"] = lots.status

            # --- history, events and outcome ---------------------------------------
            for name, spec in spec_by_name.items():
                if spec.type in _EVENT_TYPES and name not in {"pregnant"}:
                    p = parse_yes_no(raw(name)) if name in col_of else None
                    if p is None:
                        rec[name] = None
                        status[name]["absent_column"] += 1
                    else:
                        rec[name] = p.value
                        status[name][p.status] += 1
            cats = _categorise_other(raw("other_text"), norm.other_text_patterns)
            if cats == ["uncategorised"]:
                other_uncategorised[normalize_text(raw("other_text"))[:60]] += 1
            rec["other_categories"] = _join(cats)
            adm = parse_date(raw("admission_date"))
            dis = parse_date(raw("discharge_date"))
            status["admission_date"][adm.status] += 1
            status["discharge_date"][dis.status] += 1
            rec["admission_date"] = adm.value
            rec["discharge_date"] = dis.value
            records.append(rec)

        report["n_data_rows"] = n_rows
        report["junk_columns"] = [
            {
                "column": c,
                "header": cell_to_str(headers[c]) if c < len(headers) else None,
                "n_nonnull": junk_nonnull.get(c, 0),
            }
            for c in junk_cols
        ]
        schema_reports[path.name] = report
        parse_status[path.name] = {k: dict(v) for k, v in status.items()}
        ctx.step(
            "ingest_aefi_file",
            rows_out=n_rows,
            file=path.name,
            sheet=grid.sheet,
            header_row=header_idx + 1,
            n_matched=match.n_matched,
            fuzzy=len(match.fuzzy),
            unmatched=len(match.unmatched),
        )

    staging = pd.DataFrame.from_records(records)
    for col in ("vaccination_date", "notification_date", "admission_date", "discharge_date"):
        staging[col] = pd.to_datetime(staging[col], errors="raise")
    bool_cols = [
        c
        for c in staging.columns
        if c.startswith(("ev_", "hist_")) or c in {"hospitalized", "recovered", "died", "sequelae", "pregnant"}
    ]
    for col in bool_cols:
        staging[col] = staging[col].astype("boolean")
    for col in ("age_reported_months", "age_months", "age_discrepancy_months"):
        staging[col] = pd.to_numeric(staging[col], errors="raise").astype("Float64")
    for col in ("birth_year", "month_reported", "file_year", "source_row"):
        staging[col] = pd.to_numeric(staging[col], errors="raise").astype("Int64")
    ctx.step("ingest_aefi", rows_out=len(staging), files=len(files))
    return AEFIIngestResult(
        staging=staging,
        schema_reports=schema_reports,
        parse_status=parse_status,
        local_only={
            "unmapped_vaccine_tokens": dict(unmapped_vaccines.most_common()),
            "uncategorised_other_text": dict(other_uncategorised.most_common(200)),
        },
    )


def schema_drift(schema_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare mapped fields across files: which fields appear/disappear by year."""
    fields_by_file = {f: set(r["mapping"]) for f, r in schema_reports.items()}
    all_fields = set().union(*fields_by_file.values()) if fields_by_file else set()
    return {
        "fields_in_all_files": sorted(set.intersection(*fields_by_file.values())) if fields_by_file else [],
        "fields_not_in_all_files": {
            fld: sorted(f for f, s in fields_by_file.items() if fld not in s)
            for fld in sorted(all_fields)
            if any(fld not in s for s in fields_by_file.values())
        },
        "unmatched_headers": {f: r["unmatched_columns"] for f, r in schema_reports.items() if r["unmatched_columns"]},
        "fuzzy_matches": {f: r["fuzzy_matches"] for f, r in schema_reports.items() if r["fuzzy_matches"]},
    }


def today() -> dt.date:  # pragma: no cover - trivial, isolated for testability
    return dt.datetime.now(dt.UTC).date()
