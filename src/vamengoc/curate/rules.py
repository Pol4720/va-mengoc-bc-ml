"""Programme rules applied to the curated reports.

* **Vaccination schedule of the target vaccine.** Each VA-MENGOC-BC report is checked against
  the national schedule (dose 1 at 3 months, dose 2 at 5 months; valid from 3 months of age,
  two doses 6-8 weeks apart, no routine booster). A dose given below its minimum age, a dose
  number that does not exist in the schedule, or an age above the indication cannot be a valid
  administration: the row is a recording error (wrong vaccine, dose or age) and is excluded
  from the analyses, with a sensitivity analysis that keeps it. Early, late (catch-up) and
  campaign booster doses are valid and kept, with their own flag.
* **Comparator products.** Paper 1 compares the target only with the other products of the
  Finlay Vaccine Institute; other vaccines enter only as concomitant exposures.
* **Observed months.** Each annual workbook covers the months it has notifications for (the
  2023 workbook stops in July; the current year arrives month by month). Months without a
  workbook are missing, not zero, and a year with fewer than 12 observed months is partial.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from vamengoc.config import AnalysisConfig, Project

__all__ = [
    "SCHEDULE_EXCLUDED",
    "comparator_products",
    "month_coverage",
    "resolve_last_year",
    "schedule_status",
]

# Statuses that make a target administration invalid (excluded from the primary analyses).
SCHEDULE_EXCLUDED = frozenset({"too_young", "dose_not_in_schedule", "above_indication"})


def schedule_status(age_months: float | None, exact_age: bool, dose: str | None, a: AnalysisConfig) -> str:
    """Schedule category of one target administration.

    ``exact_age`` is False when the age comes only from the reported ``EDAD``, which is
    truncated to whole months (or years from 12 months): the child may be up to one unit
    older, so a dose is called too young only if even the upper bound is below the minimum.
    """
    sch = a.schedule
    if dose is None or dose in {"", "U", "nan"}:
        return "unknown_dose"
    if dose == "R":
        return "booster" if sch.booster_in_schedule else "booster_campaign"
    if dose not in sch.doses:
        return "dose_not_in_schedule"
    if age_months is None or (isinstance(age_months, float) and math.isnan(age_months)):
        return "unknown_age"
    age = float(age_months)
    upper = age if exact_age else age + (12.0 if age >= 12 else 1.0)
    rule = sch.doses[dose]
    if upper < rule.minimum_months:
        return "too_young"
    if age > sch.max_age_years * 12:
        return "above_indication"
    lo, hi = rule.routine_months
    if age < lo:
        return "early"
    if age < hi:
        return "on_schedule"
    return "late"


def apply_schedule(df: pd.DataFrame, a: AnalysisConfig) -> pd.DataFrame:
    """Add ``schedule_status`` and ``schedule_invalid`` (target reports only)."""
    exact = df["age_source"].isin(["both_agree", "derived", "conflict_derived"])
    status = [
        schedule_status(
            None if pd.isna(age) else float(age),
            bool(ex),
            None if dose is None or (isinstance(dose, float) and math.isnan(dose)) else str(dose),
            a,
        )
        if has
        else None
        for has, age, ex, dose in zip(df["has_target"], df["age_months"], exact, df["target_dose"], strict=True)
    ]
    out = df.copy()
    out["schedule_status"] = pd.Series(status, index=df.index, dtype="string")
    out["schedule_invalid"] = out["schedule_status"].isin(SCHEDULE_EXCLUDED).fillna(False).astype(bool)
    return out


def comparator_products(project: Project) -> list[str]:
    """Vaccine codes of the comparator manufacturer, excluding the target."""
    a = project.config.analysis
    if a.comparator.products is not None:
        return sorted(p for p in a.comparator.products if p != a.target_vaccine)
    vac = project.vaccines["vaccines"]
    return sorted(
        code
        for code, spec in vac.items()
        if str(spec.get("manufacturer", "")).upper() == a.comparator.manufacturer.upper() and code != a.target_vaccine
    )


def apply_comparator(df: pd.DataFrame, products: list[str]) -> pd.DataFrame:
    """Flag reports of other products of the comparator manufacturer (no target in the report)."""
    prod = set(products)

    def codes(s: Any) -> list[str]:
        if s is None or (isinstance(s, float) and np.isnan(s)) or s is pd.NA:
            return []
        return [t for t in str(s).split("|") if t]

    vac = df["vaccines"].map(codes)
    n_comp = vac.map(lambda v: len(set(v) & prod))
    out = df.copy()
    out["n_comparator_products"] = n_comp.astype(int)
    out["finlay_comparator"] = (~out["has_target"].astype(bool)) & n_comp.gt(0)
    out["concomitant_non_comparator"] = vac.map(lambda v: any(c not in prod for c in v)) & out["finlay_comparator"]
    return out


def month_coverage(df: pd.DataFrame, min_share: float = 0.1) -> pd.DataFrame:
    """Months covered by each annual workbook (``year``, ``month``, ``n_reports``, ``observed``).

    A month of year ``Y`` is observed when the workbook of ``Y`` holds notifications for it
    (from the ``MES`` column, else the notification month within ``Y``). A handful of stray
    rows (a mistyped month) does not make a month observed: it needs at least
    ``min_share`` of the median count of the workbook's months. Interior months between two
    observed months count as observed (a true zero); months after the last observed one (2023
    stops in July; the current year is still arriving) are missing.
    """
    month = df["month_reported"].astype("Float64")
    nmonth = df["notification_date"].dt.month.astype("Float64")
    in_year = df["notification_date"].dt.year.astype("Float64").eq(df["file_year"].astype("Float64"))
    m = month.where(month.notna(), nmonth.where(in_year))
    d = pd.DataFrame({"year": df["file_year"].astype("Int64"), "month": m.astype("Int64")}).dropna()
    counts = d.groupby(["year", "month"]).size()
    rows = []
    for year in sorted(df["file_year"].dropna().astype(int).unique()):
        cy = {int(mm): int(n) for (yy, mm), n in counts.items() if int(yy) == year}
        med = float(np.median(list(cy.values()))) if cy else 0.0
        present = [mm for mm, n in cy.items() if n >= max(1.0, min_share * med)]
        first, last = (min(present), max(present)) if present else (0, -1)
        for mm in range(1, 13):
            n = int(counts.get((year, mm), 0))
            rows.append({"year": int(year), "month": mm, "n_reports": n, "observed": bool(first <= mm <= last)})
    return pd.DataFrame.from_records(rows, columns=["year", "month", "n_reports", "observed"])


def resolve_last_year(configured: int | None, file_years: pd.Series) -> int:
    """Last analysed year: the configured one, or the latest workbook year when open-ended."""
    if configured is not None:
        return int(configured)
    return int(pd.to_numeric(file_years, errors="coerce").max())
