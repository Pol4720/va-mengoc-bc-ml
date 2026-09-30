"""Release guard: refuse any release that could disclose restricted data.

Checks (all must pass):

* only allowed file types, each below a size limit;
* no forbidden column names (identifiers, free text, row keys) in CSV/JSON;
* no forbidden text patterns anywhere in text files;
* no person count between 1 and ``min_cell − 1`` in the declared count columns;
* no day-precision dates in tables (only years or months are released);
* ``manifest.json`` present, consistent with the directory and with every
  file's SHA-256.

Used by ``vamengoc release verify``, the pre-commit hook and CI.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vamengoc.config import Project

__all__ = ["VerificationReport", "verify_release"]

ALLOWED_SUFFIXES = {".csv", ".json", ".tex", ".pdf", ".md", ".txt", ".svg", ".png"}
MAX_BYTES = 25 * 1024 * 1024
ALWAYS_FORBIDDEN_COLUMNS = {
    "record_id",
    "person_id",
    "row_digest",
    "source_row",
    "clinic_pseudo",
    "full_name",
    "address",
    "birth_date",
    "other_text",
    "municipality_norm",
    "health_area_norm",
    "lot_id",
    "lot_exact",
    "lot_core",
    "lots_exact",
    "target_lots",
}
_DAY_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_EXEMPT_DATE_KEYS = {"generated_utc", "started_utc", "finished_utc"}


@dataclass
class VerificationReport:
    root: Path
    errors: list[str] = field(default_factory=list)
    checked_files: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def fail(self, msg: str) -> None:
        self.errors.append(msg)


def _small(v: str, min_cell: int) -> bool:
    try:
        x = float(v)
    except ValueError:
        return False
    return 0 < x < min_cell


def _walk_json(obj: Any, path: str, cols: set[str], rep: VerificationReport, where: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in cols:
                rep.fail(f"{where}: forbidden key '{k}' at {path}")
            if isinstance(v, str) and _DAY_DATE.match(v) and str(k) not in _EXEMPT_DATE_KEYS:
                rep.fail(f"{where}: day-precision date at {path}.{k}")
            _walk_json(v, f"{path}.{k}", cols, rep, where)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_json(v, f"{path}[{i}]", cols, rep, where)


def verify_release(project: Project, root: Path) -> VerificationReport:
    rep = VerificationReport(root=root)
    cfg = project.config.sdc
    forbidden_cols = ALWAYS_FORBIDDEN_COLUMNS | set(cfg.forbidden_columns)
    patterns = [re.compile(p) for p in cfg.forbidden_patterns]
    if not root.is_dir():
        rep.fail(f"release directory {root} does not exist")
        return rep
    manifest_path = root / "manifest.json"
    schema_path = root / "tables" / "_schema.json"
    manifest: dict[str, Any] = {}
    if not manifest_path.is_file():
        rep.fail("manifest.json missing")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        origin = manifest.get("data_origin")
        if origin != root.name:
            rep.fail(f"manifest data_origin '{origin}' does not match directory '{root.name}'")
        for rel, digest in manifest.get("files", {}).items():
            p = root / rel
            if not p.is_file():
                rep.fail(f"manifest lists missing file {rel}")
            elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                rep.fail(f"checksum mismatch for {rel} (file edited after release build?)")
    schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.is_file() else {}
    listed = set(manifest.get("files", {}))
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        rep.checked_files += 1
        if p.suffix.lower() not in ALLOWED_SUFFIXES:
            rep.fail(f"{rel}: file type not allowed in a release")
            continue
        if p.stat().st_size > MAX_BYTES:
            rep.fail(f"{rel}: file larger than {MAX_BYTES} bytes")
        if manifest and rel != "manifest.json" and rel not in listed:
            rep.fail(f"{rel}: not listed in manifest (added after the build?)")
        if p.suffix.lower() in {".pdf", ".png"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for pat in patterns:
            if pat.search(text):
                rep.fail(f"{rel}: matches forbidden pattern {pat.pattern!r}")
        if p.suffix.lower() == ".csv":
            with p.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                header = reader.fieldnames or []
                bad = forbidden_cols.intersection(header)
                if bad:
                    rep.fail(f"{rel}: forbidden columns {sorted(bad)}")
                counts = set(schema.get(p.stem, {}).get("person_count_columns", []))
                for i, row in enumerate(reader, start=2):
                    for c in counts:
                        v = row.get(c, "")
                        if v and _small(v, cfg.min_cell):
                            rep.fail(f"{rel}:{i}: small person count {c}={v}")
                    for c, v in row.items():
                        if v and _DAY_DATE.match(v):
                            rep.fail(f"{rel}:{i}: day-precision date in column {c}")
        elif p.suffix.lower() == ".json":
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                rep.fail(f"{rel}: invalid JSON ({exc})")
                continue
            if rel == "web/bundle.json":
                tables = obj.get("tables", {})
                for tname, rows in tables.items():
                    counts = set(schema.get(tname, {}).get("person_count_columns", []))
                    for j, row in enumerate(rows):
                        for c in counts:
                            v = row.get(c)
                            if isinstance(v, int | float) and 0 < v < cfg.min_cell:
                                rep.fail(f"{rel}: small person count in {tname}[{j}].{c}={v}")
                _walk_json({k: v for k, v in obj.items() if k != "labels"}, "$", forbidden_cols, rep, rel)
            elif rel != "manifest.json":
                _walk_json(obj, "$", forbidden_cols, rep, rel)
    return rep
