"""Automatic data-quality assessment (no row-level output).

Checks follow the harmonised terminology of Kahn et al. (2016): *conformance*
(values parse into their declared type/domain), *completeness* (presence of
values) and *plausibility* (temporal and atemporal coherence). All results are
counts and proportions by source file / analytic year.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["DQ_CHECKS", "completeness_table", "conformance_table", "plausibility_table"]

DQ_CHECKS: dict[str, dict[str, str]] = {
    "dq_notification_before_vaccination": {
        "category": "plausibility/temporal",
        "en": "Notification date before vaccination date",
        "es": "Fecha de notificación anterior a la vacunación",
    },
    "dq_notification_delay_implausible": {
        "category": "plausibility/temporal",
        "en": "Notification delay above plausible maximum",
        "es": "Demora de notificación mayor que el máximo plausible",
    },
    "dq_birth_after_vaccination": {
        "category": "plausibility/temporal",
        "en": "Birth date after vaccination date",
        "es": "Fecha de nacimiento posterior a la vacunación",
    },
    "dq_discharge_before_admission": {
        "category": "plausibility/temporal",
        "en": "Discharge before admission",
        "es": "Egreso anterior al ingreso",
    },
    "dq_stay_implausible": {
        "category": "plausibility/temporal",
        "en": "Hospital stay above plausible maximum",
        "es": "Estadía hospitalaria mayor que el máximo plausible",
    },
    "dq_admission_before_vaccination": {
        "category": "plausibility/temporal",
        "en": "Admission before vaccination",
        "es": "Ingreso anterior a la vacunación",
    },
    "dq_age_conflict": {
        "category": "plausibility/atemporal",
        "en": "Reported age disagrees with date-derived age",
        "es": "Edad informada discrepante con la edad calculada",
    },
    "dq_age_missing": {"category": "completeness", "en": "Age not determinable", "es": "Edad no determinable"},
    "dq_age_group_mismatch": {
        "category": "plausibility/atemporal",
        "en": "Age group inconsistent with age",
        "es": "Grupo de edad inconsistente con la edad",
    },
    "dq_hospitalized_without_date": {
        "category": "plausibility/atemporal",
        "en": "Hospitalised without admission date",
        "es": "Ingresado sin fecha de ingreso",
    },
    "dq_admission_date_not_hospitalized": {
        "category": "plausibility/atemporal",
        "en": "Admission date recorded but not hospitalised",
        "es": "Fecha de ingreso registrada sin ingreso",
    },
    "dq_pregnant_male": {
        "category": "plausibility/atemporal",
        "en": "Pregnancy recorded for a male",
        "es": "Embarazo registrado en varón",
    },
    "dq_pregnant_age_implausible": {
        "category": "plausibility/atemporal",
        "en": "Pregnancy at implausible age",
        "es": "Embarazo a edad no plausible",
    },
    "dq_recovered_and_died": {
        "category": "plausibility/atemporal",
        "en": "Both recovered and died",
        "es": "Curado y fallecido a la vez",
    },
    "dq_no_event_marked": {
        "category": "completeness",
        "en": "No event indicator marked",
        "es": "Ningún evento marcado",
    },
    "dq_unmapped_vaccine": {
        "category": "conformance",
        "en": "Vaccine code not in dictionary",
        "es": "Código de vacuna fuera del diccionario",
    },
    "dq_target_lot_missing": {
        "category": "completeness",
        "en": "VA-MENGOC-BC report without lot",
        "es": "Notificación de VA-MENGOC-BC sin lote",
    },
    "dq_month_mismatch": {
        "category": "plausibility/atemporal",
        "en": "MONTH column matches neither vaccination nor notification month",
        "es": "Columna MES no coincide con el mes de vacunación ni de notificación",
    },
}


def plausibility_table(reports: pd.DataFrame, by: str = "file_year") -> pd.DataFrame:
    """Counts of each data-quality flag by ``by`` (long format)."""
    rows = []
    for key, g in reports.groupby(by, dropna=False):
        n = len(g)
        for flag, meta in DQ_CHECKS.items():
            if flag not in g:
                continue
            k = int(g[flag].fillna(False).astype(bool).sum())
            rows.append(
                {
                    by: key,
                    "check": flag,
                    "category": meta["category"],
                    "n_records": n,
                    "n_flagged": k,
                    "pct_flagged": 100.0 * k / n if n else None,
                    "label_en": meta["en"],
                    "label_es": meta["es"],
                }
            )
    return pd.DataFrame.from_records(rows)


def conformance_table(parse_status: dict[str, dict[str, dict[str, int]]]) -> pd.DataFrame:
    """Parse outcomes (ok / recovered / invalid / missing / not applicable) by file and field."""

    # Fields whose column is absent from every file (e.g. items of a form version not yet in
    # the data) carry no information and are left out; a field absent from only some files is
    # kept, so that its "absent column" count documents the change of form.
    def absent_only(counts: dict[str, int]) -> bool:
        return set(counts) <= {"absent_column"}

    everywhere_absent = {
        fld
        for fld in {f for fields in parse_status.values() for f in fields}
        if all(absent_only(fields.get(fld, {"absent_column": 0})) for fields in parse_status.values())
    }
    rows = []
    for file, fields in parse_status.items():
        for fld, counts in fields.items():
            if fld in everywhere_absent:
                continue
            total = sum(counts.values())
            rows.append(
                {"source_file": file, "field": fld, "n": total, **{f"n_{k}": int(v) for k, v in counts.items()}}
            )
    df = pd.DataFrame.from_records(rows).fillna(0)
    for c in df.columns:
        if c.startswith("n_") or c == "n":
            df[c] = df[c].astype(int)
    return df


def completeness_table(reports: pd.DataFrame, fields: list[str], by: str = "file_year") -> pd.DataFrame:
    """Share of non-missing values per field and group."""
    rows: list[dict[str, Any]] = []
    for key, g in reports.groupby(by, dropna=False):
        for f in fields:
            if f not in g:
                continue
            present = int(g[f].notna().sum())
            rows.append(
                {
                    by: key,
                    "field": f,
                    "n": len(g),
                    "n_present": present,
                    "pct_present": 100.0 * present / len(g) if len(g) else None,
                }
            )
    return pd.DataFrame.from_records(rows)
