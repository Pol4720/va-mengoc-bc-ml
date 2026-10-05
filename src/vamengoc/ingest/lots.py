"""Ingestion of the lot-release workbook: lots + specifications, national
incidence series and vaccination-coverage series.

The three sheets are independent. Their layout quirks (specification row under
the header, header on row 5, lateral cumulative block, interleaved reference
rows) are resolved by content, not by fixed cell addresses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from vamengoc.config import Project
from vamengoc.io.excel import SheetGrid, list_sheets, read_sheet
from vamengoc.io.schema_registry import (
    SchemaError,
    detect_header_row,
    fields_from_schema,
)
from vamengoc.normalize.registry import Normalizers
from vamengoc.parsing.lots import core_key, exact_key
from vamengoc.parsing.specs import Spec, parse_spec
from vamengoc.parsing.text import cell_to_str, normalize_text
from vamengoc.parsing.values import Status, parse_integer, parse_number
from vamengoc.provenance import RunContext

__all__ = ["LotsIngestResult", "find_lots_workbook", "ingest_lots_workbook"]

QUALITATIVE_PASS = {
    "organoleptic": ("CUMPLE",),
    "identity_ps": ("CUMPLE",),
    "identity_protein": ("CUMPLE",),
    "sterility": ("AUSENCIA", "CUMPLE", "ESTERIL"),
    "safety_test": ("SATISFACTORI", "CUMPLE"),
}


@dataclass
class LotsIngestResult:
    lots: pd.DataFrame
    lot_destinations: pd.DataFrame
    specs: dict[str, Spec]
    spec_report: dict[str, Any]
    incidence: pd.DataFrame
    coverage: pd.DataFrame
    coverage_cumulative: pd.DataFrame
    provenance_notes: dict[str, list[str]] = field(default_factory=dict)
    reports: dict[str, Any] = field(default_factory=dict)


def find_lots_workbook(directory: Path, pattern: str) -> Path:
    rx = re.compile(pattern)
    candidates = (
        [p for p in sorted(directory.iterdir()) if p.is_file() and rx.match(p.name) and not p.name.startswith("~$")]
        if directory.is_dir()
        else []
    )
    if not candidates:
        msg = f"No lot-release workbook matching {pattern!r} in {directory}"
        raise FileNotFoundError(msg)
    if len(candidates) > 1:
        msg = f"Several lot-release workbooks match: {[p.name for p in candidates]}"
        raise SchemaError(msg)
    return candidates[0]


def _find_sheet(path: Path, pattern: str) -> str:
    rx = re.compile(pattern)
    names = [n for n in list_sheets(path) if rx.search(n)]
    if not names:
        msg = f"{path.name}: no sheet matches {pattern!r}"
        raise SchemaError(msg)
    return names[0]


def _looks_like_spec_row(row: list[Any], col_of: dict[str, int], quantitative: list[str]) -> bool:
    """A spec row has no lot id and most quantitative cells contain operators/ranges."""
    lot_cell = row[col_of["lot_id"]] if col_of["lot_id"] < len(row) else None
    n_spec = 0
    for name in quantitative:
        c = col_of.get(name)
        if c is None or c >= len(row):
            continue
        s = cell_to_str(row[c]) or ""
        if parse_spec(s).is_quantitative and parse_number(s).value is None:
            n_spec += 1
    lot_blank = normalize_text(lot_cell) == "" or parse_spec(cell_to_str(lot_cell) or "").is_quantitative
    return n_spec >= max(2, len(quantitative) // 3) and lot_blank


def _parse_lots_sheet(
    grid: SheetGrid, project: Project, norm: Normalizers, ctx: RunContext
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Spec], dict[str, Any]]:
    sch = project.lots_schema["lots_sheet"]
    fields = fields_from_schema(sch["fields"])
    ftype = {f.name: f.type for f in fields}
    idx, match = detect_header_row(
        grid.rows,
        fields,
        max_rows=project.config.inputs.header_search_rows,
        min_matches=int(sch["min_required_matches"]),
    )
    if match.missing_required:
        msg = f"Lots sheet: required fields missing: {match.missing_required}"
        raise SchemaError(msg)
    col_of = match.field_to_column()
    quantitative = [f for f, t in ftype.items() if t == "quantitative" and f in col_of]
    qualitative = [f for f, t in ftype.items() if t == "qualitative" and f in col_of]
    min_attr = int(sch.get("min_quality_attributes", 1))
    if len(quantitative) < min_attr:
        absent = [f for f, t in ftype.items() if t == "quantitative" and f not in col_of]
        msg = (
            f"Lots sheet: only {len(quantitative)} quality attributes recognised (minimum {min_attr}); "
            f"not found: {absent}. Run `vamengoc schema-check` to see the sheet headers."
        )
        raise SchemaError(msg)
    missing_attributes = [f for f, t in ftype.items() if t == "quantitative" and f not in col_of]
    if missing_attributes:
        ctx.step("lots_attributes_not_found", attributes=missing_attributes)

    # --- specification row --------------------------------------------------------
    fallback = {
        k: Spec(op=v["op"], low=v.get("low"), high=v.get("high"), unit=v.get("unit", ""), raw="<config fallback>")
        for k, v in sch["spec_fallback"].items()
    }
    data_start = idx + 1
    parsed_specs: dict[str, Spec] = {}
    spec_text: dict[str, str | None] = {}
    if data_start < grid.n_rows and _looks_like_spec_row(grid.rows[data_start], col_of, quantitative):
        spec_row = grid.rows[data_start]
        for name in quantitative + qualitative:
            c = col_of[name]
            spec_text[name] = cell_to_str(spec_row[c]) if c < len(spec_row) else None
            parsed_specs[name] = parse_spec(spec_row[c] if c < len(spec_row) else None)
        data_start += 1
    specs: dict[str, Spec] = {}
    drift: dict[str, Any] = {}
    for name in quantitative:
        p = parsed_specs.get(name)
        fb = fallback.get(name)
        if p is not None and p.is_quantitative:
            specs[name] = p
            if fb is not None and not p.matches(fb):
                drift[name] = {"sheet": p.as_dict(), "documented": fb.as_dict()}
        elif fb is not None:
            specs[name] = fb
            drift[name] = {
                "sheet": None if p is None else p.as_dict(),
                "documented": fb.as_dict(),
                "note": "sheet specification not parseable; documented value used",
            }
    for name in qualitative:
        specs[name] = parsed_specs.get(name) or Spec(op="qualitative", raw="")

    # --- lot rows -------------------------------------------------------------------
    records: list[dict[str, Any]] = []
    dest_rows: list[dict[str, Any]] = []
    status: dict[str, dict[str, int]] = {n: {} for n in [*quantitative, "production_year"]}
    for r in range(data_start, grid.n_rows):
        row = grid.rows[r]
        lot_raw = row[col_of["lot_id"]] if col_of["lot_id"] < len(row) else None
        lot_txt = cell_to_str(lot_raw)
        if lot_txt is None or not any(ch.isdigit() for ch in lot_txt):
            # Footnotes or blank rows below the table.
            if any(v is not None and str(v).strip() for v in row):
                ctx.step("lots_sheet_skip_row", row=r + 1, reason="no lot identifier")
            continue
        rec: dict[str, Any] = {
            "source_row": r + 1,
            "lot_id": lot_txt.strip(),
            "lot_exact": exact_key(lot_txt),
            "lot_core": core_key(lot_txt),
        }
        yr = parse_integer(row[col_of["production_year"]] if col_of["production_year"] < len(row) else None)
        status["production_year"][yr.status] = status["production_year"].get(yr.status, 0) + 1
        rec["production_year"] = yr.value
        for name in quantitative:
            c = col_of[name]
            pn = parse_number(row[c] if c < len(row) else None)
            status[name][pn.status] = status[name].get(pn.status, 0) + 1
            rec[name] = pn.value
        for name in qualitative:
            c = col_of[name]
            txt = normalize_text(row[c] if c < len(row) else None)
            rec[name + "_text"] = txt or None
            if txt in {"", "-"}:
                rec[name + "_pass"] = None
            else:
                rec[name + "_pass"] = any(txt.startswith(k) for k in QUALITATIVE_PASS.get(name, ("CUMPLE",)))
        dest_raw = (
            row[col_of["destination_raw"]]
            if "destination_raw" in col_of and col_of["destination_raw"] < len(row)
            else None
        )
        dests = norm.destinations(dest_raw)
        rec["destination_codes"] = "|".join(sorted(set(dests))) if dests else None
        rec["national"] = "CU" in dests
        rec["n_destinations"] = len(set(dests))
        records.append(rec)
        for d in sorted(set(dests)):
            dest_rows.append({"lot_exact": rec["lot_exact"], "production_year": yr.value, "destination": d})

    lots = pd.DataFrame.from_records(records)
    lots["production_year"] = lots["production_year"].astype("Int64")
    for name in quantitative:
        lots[name] = pd.to_numeric(lots[name]).astype("Float64")
        spec = specs.get(name)
        if spec is not None:
            lots[name + "_conforms"] = [spec.conforms(None if pd.isna(v) else float(v)) for v in lots[name]]
    # Duplicate identifiers: keep all rows, build a composite key and report.
    dup_mask = lots.duplicated("lot_exact", keep=False)
    lots["lot_key"] = lots["lot_exact"]
    lots.loc[dup_mask, "lot_key"] = (
        lots.loc[dup_mask, "lot_exact"]
        + "@"
        + lots.loc[dup_mask, "production_year"].astype(str)
        + "#"
        + lots.loc[dup_mask].groupby(["lot_exact", "production_year"]).cumcount().add(1).astype(str)
    )
    report = {
        "sheet": grid.sheet,
        "header_row": idx + 1,
        "spec_row_detected": bool(parsed_specs),
        "spec_text": spec_text,
        "spec_drift": drift,
        "n_lots": len(lots),
        "n_duplicate_lot_ids": int(lots.loc[dup_mask, "lot_exact"].nunique()),
        "n_rows_with_duplicate_ids": int(dup_mask.sum()),
        "parse_status": status,
        "mapping": match.as_report(grid.rows[idx]),
    }
    ctx.step(
        "ingest_lots_sheet",
        rows_out=len(lots),
        duplicates=report["n_duplicate_lot_ids"],
        spec_row=report["spec_row_detected"],
        spec_drift=sorted(drift),
    )
    return lots, pd.DataFrame.from_records(dest_rows), specs, report


def _is_year(v: Any) -> int | None:
    p = parse_integer(v)
    if p.value is not None and 1900 <= p.value <= 2100:
        return p.value
    return None


def _parse_series_sheet(
    grid: SheetGrid, sch: dict[str, Any], project: Project, label: str
) -> tuple[pd.DataFrame, list[str], dict[str, Any], int]:
    fields = fields_from_schema(sch["fields"])
    idx, match = detect_header_row(
        grid.rows,
        fields,
        max_rows=project.config.inputs.header_search_rows,
        min_matches=int(sch["min_required_matches"]),
    )
    col_of = match.field_to_column()
    numeric = [f.name for f in fields if f.type == "quantitative" and f.name in col_of]
    text_fields = [f.name for f in fields if f.type == "text" and f.name in col_of]
    notes: list[str] = []
    for r in range(idx):  # titles above the header
        notes.extend(s for v in grid.rows[r] if (s := cell_to_str(v)))
    records: list[dict[str, Any]] = []
    status: dict[str, dict[str, int]] = {n: {} for n in numeric}
    main_cols = set(col_of.values())
    for r in range(idx + 1, grid.n_rows):
        row = grid.rows[r]
        year = _is_year(row[col_of["year"]] if col_of["year"] < len(row) else None)
        if year is None:
            notes.extend(s for c, v in enumerate(row) if c in main_cols and (s := cell_to_str(v)))
            continue
        rec: dict[str, Any] = {"year": year}
        for name in numeric:
            c = col_of[name]
            p = parse_number(row[c] if c < len(row) else None)
            status[name][p.status] = status[name].get(p.status, 0) + 1
            rec[name] = p.value
        for name in text_fields:
            c = col_of[name]
            s = cell_to_str(row[c]) if c < len(row) else None
            if s:
                notes.append(s)
        records.append(rec)
    df = pd.DataFrame.from_records(records).sort_values("year").reset_index(drop=True)
    for name in numeric:
        df[name] = pd.to_numeric(df[name]).astype("Float64")
    df["year"] = df["year"].astype("Int64")
    if df["year"].duplicated().any():
        msg = f"{label}: duplicated years {sorted(df.loc[df['year'].duplicated(), 'year'].tolist())}"
        raise SchemaError(msg)
    report = {
        "sheet": grid.sheet,
        "header_row": idx + 1,
        "n_years": len(df),
        "year_range": [int(df["year"].min()), int(df["year"].max())] if len(df) else None,
        "parse_status": status,
        "mapping": match.as_report(grid.rows[idx]),
    }
    return df, notes, report, max(main_cols)


def _parse_cumulative_block(grid: SheetGrid, marker: str) -> tuple[pd.DataFrame, list[str]]:
    """Extract the lateral 'total doses since 1988' block as its own table."""
    rx = re.compile(marker)
    for r in range(grid.n_rows):
        for c in range(grid.n_cols):
            s = cell_to_str(grid.cell(r, c))
            if s and rx.search(s):
                rows: list[dict[str, Any]] = []
                notes = [s]
                for rr in range(r + 1, grid.n_rows):
                    cells = [grid.cell(rr, cc) for cc in range(c, min(c + 4, grid.n_cols))]
                    year = next((y for v in cells if (y := _is_year(v)) is not None), None)
                    if year is None:
                        if any(cell_to_str(v) for v in cells):
                            notes.extend(t for v in cells if (t := cell_to_str(v)))
                            continue
                        if rows:
                            break
                        continue
                    values = [parse_number(v).value for v in cells if _is_year(v) != year]
                    nums: list[float] = [v for v in values if v is not None]
                    flags = [
                        t
                        for v in cells
                        if (t := cell_to_str(v)) and parse_number(v).value is None and _is_year(v) is None
                    ]
                    rows.append(
                        {
                            "year": year,
                            "cumulative_doses": max(nums) if nums else None,
                            "provisional": any("PROVI" in normalize_text(f) for f in flags),
                        }
                    )
                df = pd.DataFrame.from_records(rows, columns=["year", "cumulative_doses", "provisional"])
                return df, notes
    return pd.DataFrame(columns=["year", "cumulative_doses", "provisional"]), []


def ingest_lots_workbook(project: Project, path: Path, norm: Normalizers, ctx: RunContext) -> LotsIngestResult:
    ctx.register_input(path)
    pats = project.config.inputs.sheet_patterns
    lots_grid = read_sheet(path, _find_sheet(path, pats["lots"]))
    lots, dest, specs, lots_report = _parse_lots_sheet(lots_grid, project, norm, ctx)

    inc_grid = read_sheet(path, _find_sheet(path, pats["incidence"]))
    incidence, inc_notes, inc_report, _ = _parse_series_sheet(
        inc_grid, project.lots_schema["incidence_sheet"], project, "incidence"
    )
    ctx.step("ingest_incidence", rows_out=len(incidence))

    cov_grid = read_sheet(path, _find_sheet(path, pats["coverage"]))
    cov_sch = project.lots_schema["coverage_sheet"]
    coverage, cov_notes, cov_report, _ = _parse_series_sheet(cov_grid, cov_sch, project, "coverage")
    cumulative, cum_notes = _parse_cumulative_block(cov_grid, cov_sch["cumulative_block_marker"])
    # Values of the lateral block must not leak into the annual table.
    ctx.step("ingest_coverage", rows_out=len(coverage), cumulative_rows=len(cumulative))

    return LotsIngestResult(
        lots=lots,
        lot_destinations=dest,
        specs=specs,
        spec_report=lots_report,
        incidence=incidence,
        coverage=coverage,
        coverage_cumulative=cumulative,
        provenance_notes={"incidence": inc_notes, "coverage": cov_notes, "coverage_cumulative": cum_notes},
        reports={"lots": lots_report, "incidence": inc_report, "coverage": cov_report},
    )


_ = Status  # re-exported status codes are used by callers of this module
