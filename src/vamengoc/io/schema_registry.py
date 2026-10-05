"""Header detection and mapping of source columns to canonical fields.

The annual AEFI files are not guaranteed to share a layout: columns can be
renamed, reordered, added or dropped, and the header may not be on the first
row. Matching is therefore data-driven and explicit:

1. every header cell is reduced to a compact key (accent/case/punctuation
   free); a pandas-style duplicate suffix (``ASMA.1``) is read as the second
   occurrence of ``ASMA``;
2. exact alias matches are taken first, honouring ``occurrence`` for headers
   that legitimately repeat (personal vs family history);
3. remaining headers are tested against each field's ``patterns`` (regular
   expressions on the compact key, e.g. ``IGG``) and assigned only when exactly
   one field matches;
4. what is still left is matched fuzzily (rapidfuzz) only when one field wins
   clearly; pattern and fuzzy decisions are both reported for human review;
5. missing required fields raise :class:`SchemaError` — the pipeline stops
   rather than analysing a misread file.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from vamengoc.parsing.text import cell_to_str, compact

__all__ = [
    "FieldSpec",
    "HeaderMatch",
    "SchemaError",
    "detect_header_row",
    "fields_from_schema",
    "match_headers",
]

_DUP_SUFFIX = re.compile(r"^(?P<base>.*?)\.(?P<n>\d{1,2})$")


class SchemaError(ValueError):
    """Raised when a source file cannot be mapped to the declared schema."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    aliases: tuple[str, ...]
    required: bool = False
    occurrence: int = 1
    type: str = "text"
    kind: str = "category"
    patterns: tuple[str, ...] = ()


@dataclass
class HeaderMatch:
    """Result of mapping one header row."""

    columns: dict[int, str] = field(default_factory=dict)  # column index -> field
    fuzzy: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    blank_columns: list[int] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)

    @property
    def n_matched(self) -> int:
        return len(self.columns)

    def field_to_column(self) -> dict[str, int]:
        return {f: c for c, f in self.columns.items()}

    def as_report(self, headers: list[Any]) -> dict[str, Any]:
        return {
            "n_columns": len(headers),
            "n_matched": self.n_matched,
            "mapping": {f: cell_to_str(headers[c]) for c, f in sorted(self.columns.items())},
            "fuzzy_matches": self.fuzzy,
            "unmatched_columns": self.unmatched,
            "blank_header_columns": self.blank_columns,
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
        }


def fields_from_schema(fields: dict[str, dict[str, Any]]) -> list[FieldSpec]:
    out = []
    for name, spec in fields.items():
        out.append(
            FieldSpec(
                name=name,
                aliases=tuple(str(a) for a in spec.get("aliases", [])),
                required=bool(spec.get("required", False)),
                occurrence=int(spec.get("occurrence", 1)),
                type=str(spec.get("type", "text")),
                kind=str(spec.get("kind", "category")),
                patterns=tuple(str(x) for x in spec.get("patterns", [])),
            )
        )
    return out


def _header_key(value: Any) -> tuple[str, int]:
    """Compact key plus the occurrence implied by a pandas duplicate suffix."""
    s = cell_to_str(value) or ""
    m = _DUP_SUFFIX.match(s.strip())
    if m and compact(m.group("base")):
        return compact(m.group("base")), int(m.group("n")) + 1
    return compact(s), 1


def match_headers(
    headers: list[Any],
    fields: list[FieldSpec],
    *,
    fuzzy_threshold: float = 90.0,
    fuzzy_margin: float = 5.0,
) -> HeaderMatch:
    """Map header cells to canonical fields."""
    result = HeaderMatch()
    alias_index: dict[str, list[FieldSpec]] = {}
    for f in fields:
        for a in f.aliases:
            key = compact(a)
            alias_index.setdefault(key, [])
            if f not in alias_index[key]:
                alias_index[key].append(f)

    keys: list[tuple[str, int]] = []
    seen: Counter[str] = Counter()
    for h in headers:
        key, suffix_occ = _header_key(h)
        if suffix_occ > 1:
            keys.append((key, suffix_occ))
        else:
            seen[key] += 1
            keys.append((key, seen[key]))

    assigned: set[str] = set()
    pending: list[int] = []
    for col, (key, occ) in enumerate(keys):
        if not key:
            result.blank_columns.append(col)
            continue
        candidates = [f for f in alias_index.get(key, []) if f.name not in assigned]
        exact = [f for f in candidates if f.occurrence == occ]
        if not exact and candidates and occ == 1:
            exact = [f for f in candidates if f.occurrence == 1]
        if exact:
            chosen = exact[0]
            result.columns[col] = chosen.name
            assigned.add(chosen.name)
        else:
            pending.append(col)

    # Pattern pass: a field claims a header when its regular expression is the only one to match.
    if fuzzy_threshold <= 100:
        still: list[int] = []
        for col in pending:
            key, occ = keys[col]
            hits = [
                f
                for f in fields
                if f.patterns
                and f.name not in assigned
                and f.occurrence == occ
                and any(re.search(pat, key) for pat in f.patterns)
            ]
            if len(hits) == 1:
                result.columns[col] = hits[0].name
                assigned.add(hits[0].name)
                result.fuzzy.append(
                    {"column": col, "header": cell_to_str(headers[col]), "field": hits[0].name, "score": "pattern"}
                )
            else:
                still.append(col)
        pending = still

    # Fuzzy pass over headers left unmatched (skipped when disabled, e.g. header detection).
    if fuzzy_threshold > 100:
        for col in pending:
            result.unmatched.append({"column": col, "header": cell_to_str(headers[col])})
        pending = []
    alias_keys = {f.name: [compact(a) for a in f.aliases] for f in fields}
    for col in pending:
        key, occ = keys[col]
        scored: list[tuple[float, FieldSpec]] = []
        for f in fields:
            if f.name in assigned or f.occurrence != occ:
                continue
            best = max((fuzz.ratio(key, a) for a in alias_keys[f.name]), default=0.0)
            scored.append((best, f))
        scored.sort(key=lambda t: t[0], reverse=True)
        if (
            scored
            and scored[0][0] >= fuzzy_threshold
            and (len(scored) == 1 or scored[0][0] - scored[1][0] >= fuzzy_margin)
        ):
            chosen = scored[0][1]
            result.columns[col] = chosen.name
            assigned.add(chosen.name)
            result.fuzzy.append(
                {
                    "column": col,
                    "header": cell_to_str(headers[col]),
                    "field": chosen.name,
                    "score": round(scored[0][0], 1),
                }
            )
        else:
            result.unmatched.append({"column": col, "header": cell_to_str(headers[col])})

    for f in fields:
        if f.name not in assigned:
            (result.missing_required if f.required else result.missing_optional).append(f.name)
    return result


def detect_header_row(
    rows: list[list[Any]],
    fields: list[FieldSpec],
    *,
    max_rows: int = 15,
    min_matches: int = 5,
) -> tuple[int, HeaderMatch]:
    """Find the header row: the row (among the first ``max_rows``) with most exact matches."""
    best: tuple[int, HeaderMatch] | None = None
    for i, row in enumerate(rows[:max_rows]):
        m = match_headers(row, fields, fuzzy_threshold=101.0)  # exact-only for detection
        if best is None or m.n_matched > best[1].n_matched:
            best = (i, m)
    if best is None or best[1].n_matched < min_matches:
        found = 0 if best is None else best[1].n_matched
        msg = f"No header row found: best candidate matched {found} fields (< {min_matches})."
        raise SchemaError(msg)
    idx = best[0]
    return idx, match_headers(rows[idx], fields)
