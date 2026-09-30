"""Curated AEFI layer: de-duplication, analytic variables and relational tables.

Input is the pseudonymised staging table. Output:

* ``reports`` — one row per de-duplicated notification with derived analytic
  variables (analytic year, target-vaccine flags, delays, event counts, data-
  quality flags);
* relational tables following the target model of the data description
  (``administrations``, ``events``, ``history``, ``outcomes``);
* a de-duplication log (counts only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from vamengoc.config import Project
from vamengoc.provenance import RunContext

__all__ = ["CuratedAEFI", "curate_aefi", "event_columns"]

OUTCOME_COLS = ("hospitalized", "recovered", "died", "sequelae")


def event_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("ev_")]


def history_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("hist_")]


@dataclass
class CuratedAEFI:
    reports: pd.DataFrame
    administrations: pd.DataFrame
    events: pd.DataFrame
    history: pd.DataFrame
    outcomes: pd.DataFrame
    dedup_log: dict[str, Any] = field(default_factory=dict)


def _split(s: Any) -> list[str]:
    if s is None or (isinstance(s, float) and np.isnan(s)) or s is pd.NA:
        return []
    return [t for t in str(s).split("|") if t]


def _any_true(series: pd.Series) -> Any:
    """Merge rule for indicators: True if any True, else False if any False, else NA."""
    s = series.dropna()
    if s.empty:
        return pd.NA
    return bool(s.any())


def _first_valid(series: pd.Series) -> Any:
    s = series.dropna()
    return s.iloc[0] if not s.empty else pd.NA


def _deduplicate(df: pd.DataFrame, ctx: RunContext) -> tuple[pd.DataFrame, dict[str, Any]]:
    n0 = len(df)
    df = df.sort_values(["file_year", "source_file", "source_row"], kind="stable").reset_index(drop=True)
    # 1) exact duplicates of the whole source row
    exact_mask = df.duplicated("row_digest", keep="first")
    exact_by_file = df.loc[exact_mask, "source_file"].value_counts().to_dict()
    df = df.loc[~exact_mask].copy()
    n1 = len(df)

    # 2) same person + vaccination date + vaccine set + lot set (strong person keys only)
    df["vaccine_set"] = df["vaccines"].map(lambda s: "|".join(sorted(set(_split(s)))) or None)
    df["lot_set"] = df["lots_exact"].map(lambda s: "|".join(sorted(set(_split(s)))) or None)
    strong = df["person_id_strength"].eq("strong") & df["vaccination_date"].notna()
    key = ["person_id", "vaccination_date", "vaccine_set", "lot_set"]
    grp_key = df.loc[strong, key].astype(str).agg("§".join, axis=1)
    df["dedup_group"] = pd.Series(pd.NA, index=df.index, dtype="object")
    df.loc[strong, "dedup_group"] = grp_key
    dup_groups = df.loc[strong].groupby("dedup_group").size()
    multi = set(dup_groups[dup_groups > 1].index)
    is_multi = df["dedup_group"].isin(multi)
    singles = df.loc[~is_multi].copy()
    singles["n_merged"] = 1
    merged_rows = []
    bool_cols = [c for c in df.columns if str(df[c].dtype) == "boolean"]
    for gkey, g in df.loc[is_multi].groupby("dedup_group", sort=False):
        row: dict[str, Any] = {}
        for c in df.columns:
            if c in bool_cols:
                row[c] = _any_true(g[c])
            elif c == "notification_date":
                row[c] = g[c].min()
            else:
                row[c] = _first_valid(g[c])
        row["dedup_group"] = gkey
        row["n_merged"] = len(g)
        merged_rows.append(row)
    if merged_rows:
        merged = pd.DataFrame.from_records(merged_rows, columns=[*df.columns, "n_merged"])
        merged = merged.astype(
            {c: singles[c].dtype for c in singles.columns if c in merged.columns and not merged[c].isna().all()},
            errors="ignore",
        )
        # Align dtypes column by column so that concat never has to guess.
        parts = [singles.reset_index(drop=True), merged]
        out = pd.concat([p.astype(object) for p in parts], ignore_index=True)
        out = out.astype({c: singles[c].dtype for c in singles.columns}, errors="ignore")
    else:
        out = singles
    out = out.sort_values(["file_year", "source_file", "source_row"], kind="stable").reset_index(drop=True)
    for c in bool_cols:
        out[c] = out[c].astype("boolean")
    log = {
        "rows_in": n0,
        "exact_duplicates_removed": int(n0 - n1),
        "exact_duplicates_by_file": {k: int(v) for k, v in exact_by_file.items()},
        "key_duplicate_groups": len(multi),
        "key_duplicate_rows_merged": int(is_multi.sum() - len(multi)),
        "rows_out": len(out),
        "weak_person_keys": int((~df["person_id_strength"].eq("strong")).sum()),
        "rule_exact": "identical keyed digest of all mapped source cells",
        "rule_key": "same pseudonymous person + vaccination date + vaccine set + lot set; "
        "indicators merged with OR, earliest notification date kept",
    }
    ctx.step(
        "deduplicate",
        rows_in=n0,
        rows_out=len(out),
        exact=log["exact_duplicates_removed"],
        merged=log["key_duplicate_rows_merged"],
    )
    return out, log


def _target_fields(row: pd.Series, target: str) -> dict[str, Any]:
    vacc = _split(row["vaccines"])
    doses = _split(row["doses"])
    lots = _split(row["lots_exact"])
    lots_core = _split(row["lots_core"])
    mans = _split(row["manufacturers"])
    has = target in vacc
    out: dict[str, Any] = {"has_target": has, "n_vaccines": len(set(vacc))}
    dose = None
    target_lots: list[str] = []
    target_lots_core: list[str] = []
    lot_assignment = "none"
    target_man = None
    if has:
        pos = vacc.index(target)
        if len(doses) == len(vacc):
            dose = doses[pos]
        elif len(doses) == 1:
            dose = doses[0]
        if len(vacc) == 1:
            target_lots, target_lots_core = lots, lots_core
            lot_assignment = "single_vaccine" if lots else "none"
        elif lots and len(lots) == len(vacc):
            target_lots = [lots[pos]]
            target_lots_core = [lots_core[pos]] if len(lots_core) == len(lots) else []
            lot_assignment = "positional"
        elif lots:
            target_lots, target_lots_core = lots, lots_core
            lot_assignment = "ambiguous"
        if len(mans) == len(vacc):
            target_man = mans[pos]
        elif len(mans) == 1:
            target_man = mans[0]
    out["target_dose"] = dose
    out["target_dose_number"] = int(dose) if dose and dose.isdigit() else None
    out["target_booster"] = dose == "R" if dose else None
    out["target_lots"] = "|".join(target_lots) or None
    out["target_lots_core"] = "|".join(target_lots_core) or None
    out["target_lot_assignment"] = lot_assignment
    out["target_manufacturer"] = target_man
    return out


def _derive(df: pd.DataFrame, project: Project) -> pd.DataFrame:
    a = project.config.analysis
    ev = event_columns(df)
    df = df.copy()
    # Analytic year with an explicit fallback chain.
    src_map = {"vaccination_date": "vaccination_date", "notification_date": "notification_date"}
    primary = src_map.get(a.analytic_year_from)
    if primary:
        yr = df[primary].dt.year.astype("Int64")
        other = "notification_date" if primary == "vaccination_date" else "vaccination_date"
        fallback = df[other].dt.year.astype("Int64")
        df["analytic_year"] = yr.fillna(fallback).fillna(df["file_year"]).astype("Int64")
        df["analytic_year_source"] = np.where(yr.notna(), primary, np.where(fallback.notna(), other, "file_year"))
    else:
        df["analytic_year"] = df["file_year"].astype("Int64")
        df["analytic_year_source"] = "file_year"
    df["in_study_window"] = df["analytic_year"].between(*a.study_years).fillna(False).astype(bool)
    df["year_differs_from_file"] = (df["analytic_year"] != df["file_year"]).fillna(False).astype(bool)

    tf = pd.DataFrame([_target_fields(r, a.target_vaccine) for _, r in df.iterrows()], index=df.index)
    df = pd.concat([df, tf], axis=1)
    df["coadministered"] = df["n_vaccines"].gt(1)
    df["target_only"] = df["has_target"] & ~df["coadministered"]
    df["target_dose_number"] = df["target_dose_number"].astype("Int64")
    df["target_booster"] = df["target_booster"].astype("boolean")

    ev_frame = df[ev].astype("boolean")
    df["n_events"] = ev_frame.fillna(False).sum(axis=1).astype(int)
    df["n_events_unknown"] = ev_frame.isna().sum(axis=1).astype(int)
    catalogue = project.events["events"]
    serious = [c for c in ev if catalogue.get(c, {}).get("class") == "serious"]
    rare = [c for c in ev if catalogue.get(c, {}).get("class") == "rare"]
    df["any_serious_event"] = ev_frame[serious].fillna(False).any(axis=1) if serious else False
    df["any_rare_event"] = ev_frame[rare].fillna(False).any(axis=1) if rare else False
    df["fever_any"] = ev_frame[[c for c in ("ev_fever_39", "ev_fever_40") if c in ev]].fillna(False).any(axis=1)

    df["notification_delay_days"] = (df["notification_date"] - df["vaccination_date"]).dt.days.astype("Int64")
    df["los_days"] = (df["discharge_date"] - df["admission_date"]).dt.days.astype("Int64")
    df["age_years"] = (df["age_months"] / 12).astype("Float64")
    df["infant"] = df["age_months"].lt(12).astype("boolean")
    df["age_band"] = pd.cut(
        df["age_months"].astype(float),
        bins=[-0.01, 2, 4, 6, 12, 24, 72, 180, 732, 1e9],
        labels=["0-2m", "2-4m", "4-6m", "6-11m", "12-23m", "2-5y", "6-14y", "15-60y", "61y+"],
        right=False,
    ).astype("string")

    # --- data-quality flags (plausibility, Kahn et al. 2016) ------------------------
    p = a.plausibility
    df["dq_notification_before_vaccination"] = df["notification_delay_days"].lt(0).fillna(False)
    df["dq_notification_delay_implausible"] = (
        df["notification_delay_days"].gt(p.max_notification_delay_days).fillna(False)
    )
    df["dq_birth_after_vaccination"] = df["birth_after_vaccination"].astype(bool)
    df["dq_discharge_before_admission"] = df["los_days"].lt(0).fillna(False)
    df["dq_stay_implausible"] = df["los_days"].gt(p.max_hospital_stay_days).fillna(False)
    df["dq_admission_before_vaccination"] = (df["admission_date"] < df["vaccination_date"]).fillna(False)
    df["dq_age_conflict"] = df["age_source"].eq("conflict_derived")
    df["dq_age_missing"] = df["age_months"].isna()
    df["dq_age_group_mismatch"] = (
        df["age_group_reported"].notna() & df["age_group"].notna() & (df["age_group_reported"] != df["age_group"])
    )
    df["dq_hospitalized_without_date"] = (df["hospitalized"].fillna(False) & df["admission_date"].isna()).astype(bool)
    df["dq_admission_date_not_hospitalized"] = (
        df["hospitalized"].eq(False).fillna(False) & df["admission_date"].notna()
    ).astype(bool)
    df["dq_pregnant_male"] = (df["pregnant"].fillna(False) & df["sex"].eq("M")).astype(bool)
    df["dq_pregnant_age_implausible"] = (
        df["pregnant"].fillna(False) & ~df["age_years"].between(10, 55).fillna(False)
    ).astype(bool)
    df["dq_recovered_and_died"] = (df["recovered"].fillna(False) & df["died"].fillna(False)).astype(bool)
    df["dq_no_event_marked"] = df["n_events"].eq(0) & df["other_categories"].isna()
    df["dq_unmapped_vaccine"] = df["vaccines"].fillna("").str.contains("X:", regex=False)
    df["dq_target_lot_missing"] = df["has_target"] & df["target_lots"].isna()
    month_ref = df["vaccination_date"].dt.month
    df["dq_month_mismatch"] = (
        (
            df["month_reported"].notna()
            & month_ref.notna()
            & (df["month_reported"] != month_ref)
            & (df["month_reported"] != df["notification_date"].dt.month)
        )
        .fillna(False)
        .astype(bool)
    )
    return df


def _relational(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    adm_rows = []
    for rec_id, vacc, doses, lots, mans, sites, routes in df[
        ["record_id", "vaccines", "doses", "lots_exact", "manufacturers", "sites", "routes"]
    ].itertuples(index=False):
        v = _split(vacc)
        d, lt, m, s, r = _split(doses), _split(lots), _split(mans), _split(sites), _split(routes)
        for i, code in enumerate(v):

            def pick(lst: list[str], i: int = i, v: list[str] = v) -> str | None:
                if len(lst) == len(v):
                    return lst[i]
                return lst[0] if len(lst) == 1 else None

            adm_rows.append(
                {
                    "record_id": rec_id,
                    "position": i + 1,
                    "vaccine": code,
                    "dose": pick(d),
                    "lot_exact": pick(lt),
                    "manufacturer": pick(m),
                    "site": pick(s),
                    "route": pick(r),
                }
            )
    administrations = pd.DataFrame.from_records(
        adm_rows, columns=["record_id", "position", "vaccine", "dose", "lot_exact", "manufacturer", "site", "route"]
    )
    ev = event_columns(df)
    events = df.melt(id_vars=["record_id"], value_vars=ev, var_name="event", value_name="present")
    events["present"] = events["present"].astype("boolean")
    hc = history_columns(df)
    history = df.melt(id_vars=["record_id"], value_vars=hc, var_name="condition", value_name="present")
    history["type"] = np.where(history["condition"].str.startswith("hist_personal"), "personal", "family")
    history["condition"] = history["condition"].str.replace(r"^hist_(personal|family)_", "", regex=True)
    history["present"] = history["present"].astype("boolean")
    outcomes = df[["record_id", *OUTCOME_COLS, "admission_date", "discharge_date", "los_days"]].copy()
    return administrations, events, history, outcomes


def curate_aefi(staging: pd.DataFrame, project: Project, ctx: RunContext) -> CuratedAEFI:
    dedup, log = _deduplicate(staging, ctx)
    reports = _derive(dedup, project)
    ctx.step(
        "derive_analytic_variables",
        rows_in=len(dedup),
        rows_out=len(reports),
        in_window=int(reports["in_study_window"].sum()),
        target_reports=int(reports["has_target"].sum()),
    )
    administrations, events, history, outcomes = _relational(reports)
    return CuratedAEFI(
        reports=reports,
        administrations=administrations,
        events=events,
        history=history,
        outcomes=outcomes,
        dedup_log=log,
    )
