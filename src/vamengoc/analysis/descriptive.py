"""Descriptive epidemiology of AEFI reports (Table 1-type summaries)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from vamengoc.curate.aefi_model import event_columns

__all__ = ["characteristics_table", "event_frequency_table", "reports_by_year"]


def _group_label(df: pd.DataFrame, target: str) -> pd.Series:
    return pd.Series(np.where(df["has_target"], target, "Other vaccines"), index=df.index)


def characteristics_table(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Long table: variable, level, group, n, denominator, pct."""
    d = df.copy()
    d["group"] = _group_label(d, target)
    rows: list[dict[str, Any]] = []
    groups = [target, "Other vaccines", "All"]

    def add(variable: str, series: pd.Series, dropna: bool = False) -> None:
        for g in groups:
            s = series if g == "All" else series[d["group"] == g]
            denom = int(s.notna().sum()) if dropna else len(s)
            counts = s.value_counts(dropna=dropna)
            for level, n in counts.items():
                rows.append(
                    {
                        "variable": variable,
                        "level": "Missing" if pd.isna(level) else str(level),
                        "group": g,
                        "n": int(n),
                        "denominator": denom,
                        "pct": 100.0 * n / denom if denom else np.nan,
                    }
                )

    add("sex", d["sex"])
    add("age_group", d["age_group"])
    add("age_band", d["age_band"])
    add("region", d["region"])
    add("coadministered", d["coadministered"].map({True: "Yes", False: "No"}))
    add("dose", d["target_dose"].where(d["has_target"], d["doses"]))
    add("place", d["place"])
    add("hospitalized", d["hospitalized"].map({True: "Yes", False: "No"}))
    add("any_serious_event", d["any_serious_event"].map({True: "Yes", False: "No"}))
    add("pregnant", d["pregnant"].map({True: "Yes", False: "No"}))
    out = pd.DataFrame.from_records(rows)
    # continuous summaries
    cont = []
    for g in groups:
        s = d["age_months"] if g == "All" else d.loc[d["group"] == g, "age_months"]
        s = pd.to_numeric(s, errors="coerce").dropna().astype(float)
        cont.append(
            {
                "variable": "age_months",
                "group": g,
                "n": len(s),
                "median": float(s.median()) if len(s) else np.nan,
                "q1": float(s.quantile(0.25)) if len(s) else np.nan,
                "q3": float(s.quantile(0.75)) if len(s) else np.nan,
            }
        )
        s2 = d["notification_delay_days"] if g == "All" else d.loc[d["group"] == g, "notification_delay_days"]
        s2 = pd.to_numeric(s2, errors="coerce").dropna().astype(float)
        s2 = s2[s2 >= 0]
        cont.append(
            {
                "variable": "notification_delay_days",
                "group": g,
                "n": len(s2),
                "median": float(s2.median()) if len(s2) else np.nan,
                "q1": float(s2.quantile(0.25)) if len(s2) else np.nan,
                "q3": float(s2.quantile(0.75)) if len(s2) else np.nan,
            }
        )
    out.attrs["continuous"] = pd.DataFrame.from_records(cont)
    return out


def event_frequency_table(df: pd.DataFrame, target: str, labels: dict[str, dict[str, str]]) -> pd.DataFrame:
    """Frequency of each event indicator among reports of the target and of other vaccines."""
    rows = []
    for ev in event_columns(df):
        for g, mask in (
            (target, df["has_target"]),
            ("Other vaccines", ~df["has_target"]),
            ("All", pd.Series(True, index=df.index)),
        ):
            s = df.loc[mask, ev].astype("boolean")
            known = int(s.notna().sum())
            n = int(s.fillna(False).sum())
            rows.append(
                {
                    "event": ev,
                    "group": g,
                    "n": n,
                    "denominator": known,
                    "pct": 100.0 * n / known if known else np.nan,
                    "label_en": labels.get(ev, {}).get("label_en", ev),
                    "label_es": labels.get(ev, {}).get("label_es", ev),
                    "class": labels.get(ev, {}).get("class"),
                    "domain": labels.get(ev, {}).get("domain"),
                }
            )
    return pd.DataFrame.from_records(rows)


def reports_by_year(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Annual counts of all reports and of target-vaccine reports."""
    g = df.groupby("analytic_year")
    out = pd.DataFrame(
        {
            "n_reports": g.size(),
            "n_target": g["has_target"].sum(),
            "n_target_only": g["target_only"].sum(),
            "n_hospitalized": g["hospitalized"].apply(lambda s: int(s.fillna(False).sum())),
            "n_target_hospitalized": g.apply(
                lambda x: int((x["has_target"] & x["hospitalized"].fillna(False)).sum()), include_groups=False
            ),
        }
    ).reset_index()
    out["target"] = target
    return out
