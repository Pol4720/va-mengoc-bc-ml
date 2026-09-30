"""Record linkage of VA-MENGOC-BC AEFI reports to released lots.

Linkage is deterministic first and fuzzy last, with every decision labelled so
that analyses can be restricted to high-confidence links:

1. ``exact``  — identical upper-case alphanumeric key;
2. ``core``   — same digits and letters in any order (``M575`` ≙ ``575M``),
   accepted only if it points to a single lot;
3. ``fuzzy``  — rapidfuzz ratio ≥ threshold against national lots produced in a
   plausible window, accepted only when the best candidate is unique.

Among several lots with the same identifier (the workbook contains duplicated
IDs), national lots and the most recent production year not later than the
vaccination year are preferred; a remaining tie is left unlinked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from rapidfuzz import fuzz, process

from vamengoc.config import Project
from vamengoc.provenance import RunContext

__all__ = ["LinkageResult", "link_reports_to_lots"]

LEVELS = ("exact", "core", "fuzzy")


@dataclass
class LinkageResult:
    links: pd.DataFrame  # one row per linked target report
    summary: dict[str, Any] = field(default_factory=dict)
    bias_table: pd.DataFrame = field(default_factory=pd.DataFrame)


def _choose(cands: pd.DataFrame, vacc_year: int | None) -> tuple[pd.Series | None, str]:
    """Pick one lot among candidates sharing an identifier."""
    if cands.empty:
        return None, "none"
    if len(cands) == 1:
        return cands.iloc[0], "unique"
    c = cands
    if c["national"].any():
        c = c[c["national"]]
    if vacc_year is not None:
        prior = c[c["production_year"].fillna(9999) <= vacc_year]
        if not prior.empty:
            c = prior
        best_year = c["production_year"].max()
        c = c[c["production_year"] == best_year]
    if len(c) == 1:
        return c.iloc[0], "disambiguated"
    return None, "ambiguous"


def link_reports_to_lots(reports: pd.DataFrame, lots: pd.DataFrame, project: Project, ctx: RunContext) -> LinkageResult:
    cfg = project.config.analysis.linkage
    target = reports[reports["has_target"] & reports["in_study_window"]].copy()
    # Explicit comprehensions: dict(groupby) fails because GroupBy exposes a `keys` attribute.
    by_exact = {k: g for k, g in lots.groupby("lot_exact")}  # noqa: C416
    by_core = {k: g for k, g in lots.dropna(subset=["lot_core"]).groupby("lot_core")}  # noqa: C416
    national = lots[lots["national"]]
    national_keys = national["lot_exact"].tolist()

    rows: list[dict[str, Any]] = []
    for rec in target.itertuples(index=False):
        vacc_year = int(rec.analytic_year) if pd.notna(rec.analytic_year) else None
        keys = [k for k in str(rec.target_lots).split("|") if k] if isinstance(rec.target_lots, str) else []
        cores = list(str(rec.target_lots_core).split("|")) if isinstance(rec.target_lots_core, str) else []
        hits: list[tuple[pd.Series, str, str]] = []
        reasons: list[str] = []
        for i, key in enumerate(keys):
            cand = by_exact.get(key)
            chosen, why = _choose(cand if cand is not None else lots.iloc[0:0], vacc_year)
            if chosen is not None:
                hits.append((chosen, "exact", why))
                continue
            if why == "ambiguous":
                reasons.append("ambiguous_duplicate_id")
                continue
            core = cores[i] if i < len(cores) else ""
            if core:
                cand = by_core.get(core)
                chosen, why = _choose(cand if cand is not None else lots.iloc[0:0], vacc_year)
                if chosen is not None:
                    hits.append((chosen, "core", why))
                    continue
                if why == "ambiguous":
                    reasons.append("ambiguous_core")
                    continue
            if cfg.allow_fuzzy and national_keys and len(key) >= 3:
                pool = national
                if vacc_year is not None:
                    pool = national[
                        national["production_year"].between(vacc_year - cfg.max_years_after_production, vacc_year)
                    ]
                if not pool.empty:
                    res = process.extract(key, pool["lot_exact"].tolist(), scorer=fuzz.ratio, limit=2)
                    if res and res[0][1] >= cfg.fuzzy_threshold and (len(res) == 1 or res[0][1] - res[1][1] >= 3):
                        chosen = pool.iloc[res[0][2]]
                        hits.append((chosen, "fuzzy", f"score={round(res[0][1])}"))
                        continue
            reasons.append("no_match")
        distinct = {h[0]["lot_key"] for h in hits}
        base = {
            "record_id": rec.record_id,
            "analytic_year": rec.analytic_year,
            "n_target_lot_tokens": len(keys),
            "lot_assignment": rec.target_lot_assignment,
        }
        if not keys:
            rows.append(
                {**base, "lot_key": None, "match_level": "no_lot_recorded", "n_linked_lots": 0, "temporal_ok": None}
            )
        elif len(distinct) == 1:
            lot, level, _why = hits[0]
            best = min(hits, key=lambda h: LEVELS.index(h[1]))
            lot, level = best[0], best[1]
            py = lot["production_year"]
            temporal_ok = (
                None
                if vacc_year is None or pd.isna(py)
                else bool(py <= vacc_year <= py + cfg.max_years_after_production)
            )
            rows.append(
                {
                    **base,
                    "lot_key": lot["lot_key"],
                    "match_level": level,
                    "n_linked_lots": 1,
                    "temporal_ok": temporal_ok,
                    "national_lot": bool(lot["national"]),
                }
            )
        elif len(distinct) > 1:
            rows.append(
                {
                    **base,
                    "lot_key": None,
                    "match_level": "multiple_lots",
                    "n_linked_lots": len(distinct),
                    "temporal_ok": None,
                }
            )
        else:
            rows.append(
                {
                    **base,
                    "lot_key": None,
                    "match_level": reasons[0] if reasons else "no_match",
                    "n_linked_lots": 0,
                    "temporal_ok": None,
                }
            )
    links = pd.DataFrame.from_records(rows)
    if links.empty:
        links = pd.DataFrame(
            columns=["record_id", "analytic_year", "lot_key", "match_level", "n_linked_lots", "temporal_ok"]
        )
    linked = links["lot_key"].notna()
    by_level = links["match_level"].value_counts().to_dict()
    by_year = (
        links.assign(linked=linked)
        .groupby("analytic_year")["linked"]
        .agg(["size", "sum"])
        .rename(columns={"size": "n_reports", "sum": "n_linked"})
        .reset_index()
    )
    summary = {
        "n_target_reports": len(links),
        "n_linked": int(linked.sum()),
        "link_rate": float(linked.mean()) if len(links) else None,
        "by_level": {k: int(v) for k, v in by_level.items()},
        "n_distinct_lots_linked": int(links.loc[linked, "lot_key"].nunique()),
        "temporal_implausible": int((links["temporal_ok"] == False).sum()),  # noqa: E712
        "by_year": by_year.to_dict(orient="records"),
    }
    # Linkage-bias table: do linked and unlinked reports differ?
    tgt = target.merge(links[["record_id"]].assign(linked=linked.values), on="record_id", how="left")
    num = pd.DataFrame(
        {
            "linked": tgt["linked"].astype(bool),
            "age_months": pd.to_numeric(tgt["age_months"], errors="coerce").astype(float),
            "female": tgt["sex"].eq("F").astype(float),
            "fever39": tgt["ev_fever_39"].astype("boolean").fillna(False).astype(float),
            "hospitalized": tgt["hospitalized"].astype("boolean").fillna(False).astype(float),
            "coadministered": tgt["coadministered"].astype(float),
        }
    )
    grouped = num.groupby("linked")
    bias = pd.DataFrame(
        {
            "n": grouped.size(),
            "age_months_median": grouped["age_months"].median(),
            "female_pct": 100 * grouped["female"].mean(),
            "fever39_pct": 100 * grouped["fever39"].mean(),
            "hospitalized_pct": 100 * grouped["hospitalized"].mean(),
            "coadministered_pct": 100 * grouped["coadministered"].mean(),
        }
    ).reset_index()
    ctx.step("link_reports_to_lots", rows_in=len(target), rows_out=int(linked.sum()), by_level=summary["by_level"])
    return LinkageResult(links=links, summary=summary, bias_table=bias)
