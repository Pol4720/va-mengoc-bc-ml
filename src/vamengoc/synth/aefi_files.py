"""Synthetic annual AEFI workbooks (``EA_<YEAR>_TOTAL.xlsx``).

The generator reproduces the structure and every documented defect of the
real files — without using any real record. Names and addresses are
fabricated from generic lists. Schema variations are introduced across years
(renamed, reordered, added and missing columns; header not on the first row)
so that the ingestion code is exercised against layout drift.

A latent reactogenicity phenotype drives the co-occurrence of event
indicators, and an optional planted association between lot endotoxin
content and fever lets the quality-safety analysis be validated against a
known truth.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook

__all__ = ["BASE_HEADER", "EVENT_HEADERS", "AEFISynthConfig", "generate_aefi"]

EVENT_HEADERS = [
    "ABS.ESTERIL",
    "ABS.BACTERIAN",
    "LINFADENITIS",
    "R.L.S",
    "P.AGUDA",
    "ENCEFALOPATIAS",
    "C.DE CONDUCTA",
    "DAÑO CEREBRAL",
    "ENCEFALITIS",
    "MENINGITIS",
    "R.ALERGICA",
    "C.FEBRIL",
    "C.AFEBRIL",
    "R.ANAFILACTICA",
    "SHOCK ANAFIL.",
    "ARTRALGIAS",
    "FIEBRE 39",
    "FIEBRE 40",
    "COLAPSO",
    "OSTEI/OSTEO",
    "LLANTO PERSST.",
    "SEPSS",
    "SHOCK TOXICO",
    "RASH",
    "PURPURA",
    "OTROS",
]
EVENT_KEYS = [
    "sterile_abscess",
    "bacterial_abscess",
    "lymphadenitis",
    "severe_local_reaction",
    "acute_paralysis",
    "encephalopathy",
    "behaviour_change",
    "brain_damage",
    "encephalitis",
    "meningitis",
    "allergic_reaction",
    "febrile_seizure",
    "afebrile_seizure",
    "anaphylactic_reaction",
    "anaphylactic_shock",
    "arthralgia",
    "fever_39",
    "fever_40",
    "collapse",
    "osteitis",
    "persistent_crying",
    "sepsis",
    "toxic_shock",
    "rash",
    "purpura",
    "other",
]
BASE_HEADER = [
    "NOMBRES Y APELLIDOS",
    "SEXO",
    "F.NACIMIENTO",
    "EDAD",
    "GRUPO DE EDAD",
    "DIRECCION",
    "CONSULTORIO",
    "AREA DE SALUD",
    "MUNICIPIO",
    "PROVINCIAS",
    "EMBARAZADA",
    "MES",
    "F.VACUNACION",
    "F.NOTIFICACION",
    "TIPO DE VACUNA",
    "Dosis",
    "S.APLICACION",
    "V.ADMON.",
    "L.APLICACION",
    "FABRICNATE",
    "LOTE",
    "APP ALERGIA",
    "CONVULSON",
    "ASMA",
    "APF ALERGIA",
    "CONVULSON",
    "ASMA",
    *EVENT_HEADERS,
    "CUAL (otro)",
    "INGRESO",
    "F.INGRESO",
    "F.EGRESO",
    "CURADO",
    "FALLECIDO",
    "SECUELA",
    None,
]

_GIVEN = [
    "Ana",
    "Luis",
    "María",
    "José",
    "Yanet",
    "Carlos",
    "Yudith",
    "Raúl",
    "Dayana",
    "Pedro",
    "Lianet",
    "Jorge",
    "Yoandra",
    "Alejandro",
    "Mailén",
    "Ernesto",
    "Daniela",
    "Osmany",
    "Claudia",
    "Yasiel",
    "Leidy",
    "Frank",
    "Arianna",
    "Rolando",
    "Zulema",
    "Adrián",
    "Idalmis",
    "Reinier",
    "Yuniel",
    "Marlene",
    "Dariel",
    "Yaquelín",
    "Orlando",
    "Beatriz",
    "Yunior",
]
_SURN = [
    "Pérez",
    "González",
    "Rodríguez",
    "Hernández",
    "García",
    "Fernández",
    "López",
    "Díaz",
    "Martínez",
    "Sánchez",
    "Álvarez",
    "Romero",
    "Suárez",
    "Castillo",
    "Ramírez",
    "Torres",
    "Morales",
    "Reyes",
    "Cruz",
    "Ortiz",
    "Delgado",
    "Vega",
    "Rivero",
    "Cabrera",
    "Mesa",
    "Batista",
    "Leyva",
    "Ávila",
    "Guerra",
    "Estrada",
    "Peña",
    "Rojas",
    "Montero",
    "Fonseca",
]
_STREETS = ["Calle", "Ave.", "Calzada", "Carretera", "Callejón"]
PROVINCES = [
    ("PR", 0.052),
    ("AT", 0.045),
    ("LH", 0.19),
    ("MY", 0.034),
    ("MT", 0.063),
    ("IJ", 0.008),
    ("VC", 0.068),
    ("CF", 0.036),
    ("SS", 0.041),
    ("CA", 0.039),
    ("CM", 0.068),
    ("LT", 0.048),
    ("HO", 0.092),
    ("GM", 0.074),
    ("SC", 0.093),
    ("GT", 0.045),
]
_MUNIS = {
    "PR": ["Pinar del Río", "Consolación del Sur", "Guane"],
    "AT": ["Artemisa", "Bauta"],
    "LH": ["Plaza", "Playa", "Boyeros", "Diez de Octubre", "Centro Habana"],
    "MY": ["San José", "Güines"],
    "MT": ["Matanzas", "Cárdenas"],
    "IJ": ["Nueva Gerona"],
    "VC": ["Santa Clara", "Placetas"],
    "CF": ["Cienfuegos"],
    "SS": ["Sancti Spíritus", "Trinidad"],
    "CA": ["Ciego de Ávila", "Morón"],
    "CM": ["Camagüey", "Florida"],
    "LT": ["Las Tunas"],
    "HO": ["Holguín", "Banes", "Moa"],
    "GM": ["Bayamo", "Manzanillo"],
    "SC": ["Santiago de Cuba", "Palma Soriano"],
    "GT": ["Guantánamo", "Baracoa"],
}

# vaccine label, probability, manufacturer label variants, schedule kind
VACCINES: list[tuple[str, float]] = [
    ("PENTA-L", 0.50),
    ("AM-BC", 0.17),
    ("PENTA-L,IPV", 0.04),
    ("DPT", 0.05),
    ("DPT+Hib", 0.03),
    ("Hib+DPT", 0.01),
    ("PRS", 0.05),
    ("AG", 0.03),
    ("TT", 0.02),
    ("OPV", 0.01),
    ("IPV", 0.01),
    ("Hib", 0.01),
    ("AT", 0.01),
    ("HB", 0.02),
    ("DT", 0.01),
    ("AA", 0.005),
    ("AL", 0.01),
    ("BCG", 0.005),
    ("IPV,PENTA-L", 0.01),
    ("AM-BC,PENTA-L", 0.005),
]
_AMBC_VARIANTS = ["AM-BC"] * 30 + ["AMBC", "am-bc", "AM BC", "AM-BC ", "VA-MENGOC-BC"]
_MANUF = {
    "AM-BC": ["Instituto Finlay", "Finlay", "IFV", "finlay ", "Inst. Finlay", "INSTITUTO FINLAY", "Intituto Finlay"],
    "PENTA-L": ["Heber Biotec", "heberbiotec", "heber- biotec", "CIGB", "Heber biotec", "HEBERBIOTEC"],
    "DPT": ["Finlay", "Instituto Finlay"],
    "DT": ["Finlay"],
    "TT": ["Finlay"],
    "AT": ["Finlay"],
    "AL": ["Finlay"],
    "HIB": ["CIGB", "Heber Biotec"],
    "HB": ["Heber Biotec", "CIGB"],
    "PRS": ["Serum Institute of India", "Serum Institute", "SII", "serum institute of india"],
    "AG": ["Sanofi Pasteur", "Serum Institute of India"],
    "OPV": ["Bio Farma", "Serum Institute of India"],
    "IPV": ["Serum Institute of India"],
    "AA": ["Bio Farma"],
    "BCG": ["Serum Institute of India"],
}
# latent reactogenicity phenotypes: event probabilities
PHENOTYPES: dict[str, dict[str, float]] = {
    "febrile": {"fever_39": 0.95, "fever_40": 0.12, "persistent_crying": 0.05, "febrile_seizure": 0.01, "other": 0.15},
    "local": {
        "severe_local_reaction": 0.85,
        "fever_39": 0.35,
        "lymphadenitis": 0.05,
        "sterile_abscess": 0.03,
        "bacterial_abscess": 0.005,
        "other": 0.25,
    },
    "allergic": {"rash": 0.6, "allergic_reaction": 0.5, "fever_39": 0.2, "other": 0.3, "anaphylactic_reaction": 0.004},
    "neuro": {
        "febrile_seizure": 0.35,
        "afebrile_seizure": 0.08,
        "collapse": 0.25,
        "persistent_crying": 0.3,
        "fever_39": 0.6,
        "behaviour_change": 0.05,
        "fever_40": 0.2,
    },
    "other": {"other": 0.9, "fever_39": 0.3, "arthralgia": 0.08},
}
PHENO_BY_GROUP = {
    "PENTA": [0.70, 0.15, 0.04, 0.03, 0.08],
    "AMBC": [0.60, 0.27, 0.04, 0.02, 0.07],
    "DPT": [0.65, 0.20, 0.03, 0.04, 0.08],
    "PRS": [0.45, 0.05, 0.25, 0.02, 0.23],
    "ADULT": [0.20, 0.35, 0.10, 0.005, 0.345],
    "OTHER": [0.40, 0.25, 0.05, 0.01, 0.29],
}
RARE_SERIOUS = {
    "encephalopathy": 3e-4,
    "encephalitis": 2e-4,
    "meningitis": 2e-4,
    "brain_damage": 1e-4,
    "acute_paralysis": 2e-4,
    "sepsis": 3e-4,
    "toxic_shock": 1e-4,
    "osteitis": 2e-4,
    "purpura": 4e-4,
    "anaphylactic_shock": 2e-4,
}
_OTHER_TEXT = [
    "Vómitos",
    "Irritabilidad",
    "Dolor y aumento de volumen",
    "Diarrea",
    "Somnolencia",
    "Tos y catarro",
    "Urticaria",
    "Decaimiento",
    "inapetencia",
    "Febrícula",
    "Eritema local",
    "llanto e irritabilidad",
    "cefalea",
    "Nódulo en sitio de inyección",
]


@dataclass
class AEFISynthConfig:
    years: tuple[int, ...] = tuple(range(2017, 2026))
    reports_per_year: int = 7700
    scale: float = 1.0
    seed: int = 11
    exact_duplicate_rate: float = 0.015
    key_duplicate_rate: float = 0.004
    endotoxin_log_or_per_sd: float = float(np.log(1.25))  # planted lot effect on fever ≥39 (AM-BC)
    schema_variations: bool = True
    national_lots: pd.DataFrame | None = None  # from the lot generator
    extra: dict[str, Any] = field(default_factory=dict)


def _vaccine_group(label: str) -> str:
    first = label.split(",", maxsplit=1)[0].split("+", maxsplit=1)[0].upper()
    if "AM" in first and "BC" in first:
        return "AMBC"
    if first.startswith("PENTA"):
        return "PENTA"
    if first in {"DPT", "HIB"}:
        return "DPT"
    if first == "PRS":
        return "PRS"
    if first in {"AG", "TT", "AT", "AL", "AA", "HB", "DT"}:
        return "ADULT"
    return "OTHER"


def _age_days(rng: np.random.Generator, label: str) -> tuple[int, str]:
    """Age at vaccination (days) and dose token according to a schedule."""
    first = label.split(",", maxsplit=1)[0].split("+", maxsplit=1)[0].upper()
    j = int(rng.integers(-6, 12))
    if first.startswith("PENTA") or first in {"OPV", "IPV"}:
        dose = str(rng.choice(["1", "2", "3", "R"], p=[0.36, 0.32, 0.27, 0.05]))
        m = {"1": 2, "2": 4, "3": 6, "R": 18}[dose]
        return int(m * 30.44 + j), dose
    if first in {"AM-BC", "AMBC", "VA-MENGOC-BC", "AM BC"}:
        if rng.random() < 0.03:
            return int(rng.integers(365, 5 * 365)), "1"
        dose = str(rng.choice(["1", "2"], p=[0.55, 0.45]))
        return int((3 if dose == "1" else 5) * 30.44 + j), dose
    if first in {"DPT", "HIB"}:
        return int(18 * 30.44 + j), "R"
    if first == "PRS":
        dose = str(rng.choice(["1", "2"], p=[0.7, 0.3]))
        return (int(12 * 30.44 + j) if dose == "1" else int(6 * 365.25 + j)), dose
    if first == "BCG":
        return int(rng.integers(0, 5)), "U"
    if first == "HB":
        if rng.random() < 0.5:
            return int(rng.integers(0, 3)), "1"
        return int(rng.integers(18 * 365, 60 * 365)), str(rng.choice(["1", "2", "3"]))
    if first == "DT":
        return int(6 * 365.25 + j), "R"
    if first == "AG":
        if rng.random() < 0.6:
            return int(rng.integers(61 * 365, 90 * 365)), "U"
        return int(rng.integers(183, 5 * 365)), "U"
    return int(rng.integers(15 * 365, 60 * 365)), str(rng.choice(["1", "2", "R"]))


def _edad_text(rng: np.random.Generator, days: int) -> str:
    if days < 7 and rng.random() < 0.5:
        return "RN"
    if days < 30:
        return f"{max(days, 1)} D"
    months = int(days / 30.44)
    if months < 24:
        fmt = rng.choice(["{m}M", "{m} m", "{m} M", "{m}m", "{m} MESES", "{m}M "])
        return str(fmt).format(m=months)
    years = int(days / 365.25)
    fmt = rng.choice(["{y}A", "{y} a", "{y} A", "{y} AÑOS", "{y}a"])
    return str(fmt).format(y=years)


def _group_text(days: int) -> str:
    y = days / 365.25
    if y < 6:
        return "0 a 5"
    if y < 15:
        return "6 a 14"
    if y < 61:
        return "15 a 60"
    return "61 y +"


def _yn(rng: np.random.Generator, value: bool, p_missing: float = 0.008) -> Any:
    if rng.random() < p_missing:
        return None
    if value:
        return str(rng.choice(["S", "S", "S", "s", "S "]))
    return str(rng.choice(["N"] * 20 + ["N ", " N", "n", "        N"]))


def _date_cell(rng: np.random.Generator, d: dt.date | None, as_text: bool) -> Any:
    if d is None:
        return None
    if as_text or rng.random() < 0.004:
        return d.strftime(str(rng.choice(["%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"])))
    if rng.random() < 0.002:
        return (d - dt.date(1899, 12, 30)).days  # Excel serial number stored as a number
    return dt.datetime(d.year, d.month, d.day)


def _lot_cell(rng: np.random.Generator, lot: str) -> Any:
    r = rng.random()
    if r < 0.55:
        return lot
    if r < 0.65:
        return lot.lower()
    if r < 0.72:
        return lot.replace("M", " M") if lot.endswith("M") else lot.replace("M", "M ")
    if r < 0.78:  # letter moved: 575M -> M575 (core-key match)
        digits = "".join(ch for ch in lot if ch.isdigit())
        return "M" + digits if lot.endswith("M") else digits + "M"
    if r < 0.82:  # typo: one digit changed (fuzzy or unmatched)
        chars = list(lot)
        idx = [i for i, ch in enumerate(chars) if ch.isdigit()]
        if idx:
            k = int(rng.choice(idx))
            chars[k] = str((int(chars[k]) + 1) % 10)
        return "".join(chars)
    if r < 0.86:  # a lot that is not in the release workbook
        return f"{int(rng.integers(1, 99)):02d}{rng.choice(['A', 'B'])}{int(rng.integers(100, 999))}"
    return f"{lot}-"


def _other_lot(rng: np.random.Generator) -> Any:
    r = rng.random()
    n = int(rng.integers(1000, 9999))
    if r < 0.4:
        return n
    if r < 0.5:
        return float(n)
    if r < 0.8:
        return f"{rng.choice(['A', 'B', 'C', 'P'])}{n}"
    if r < 0.95:
        return f"{n}/{n + 1}"
    return f"L{n}"


def _choose_ambc_lot(rng: np.random.Generator, lots: pd.DataFrame | None, year: int) -> tuple[str | None, float]:
    if lots is None or lots.empty:
        return f"{int(rng.integers(500, 900))}M", 0.0
    pool = lots[(lots["production_year"] <= year) & (lots["production_year"] >= year - 3)]
    if pool.empty:
        pool = lots
    w = np.exp(-(year - pool["production_year"].to_numpy()) / 1.5)
    i = int(rng.choice(len(pool), p=w / w.sum()))
    row = pool.iloc[i]
    return str(row["lot_id"]), float(row["z_endotoxin"])


def _expit(x: float) -> float:
    return float(1 / (1 + np.exp(-x)))


def _dose_cell(rng: np.random.Generator, doses: list[str]) -> Any:
    if len(doses) == 1:
        d = doses[0]
        if rng.random() < 0.3 and d.isdigit():
            return int(d)
        return d
    a, b = doses[0], doses[1]
    r = rng.random()
    if a.isdigit() and b.isdigit():
        if r < 0.3:
            return float(f"{a}.{b}")  # "2,1" read as a decimal
        if r < 0.4 and int(a) <= 5 and int(b) <= 12 and a != "0":
            return dt.datetime(2017, int(b), int(a))  # "1/2" read as a date
        if r < 0.5 and a == "1" and b == "2":
            return 0.5  # "1/2" read as a fraction
    if r < 0.8:
        return f"{a},{b}"
    return f"{a} y {b}"


def _one_record(
    rng: np.random.Generator, year: int, cfg: AEFISynthConfig, person: dict[str, Any] | None, allow_2016: bool
) -> dict[str, Any]:
    labels, probs = zip(*VACCINES, strict=True)
    p = np.array(probs) / np.sum(probs)
    label = str(rng.choice(labels, p=p))
    group = _vaccine_group(label)
    age_days, dose = _age_days(rng, label)
    start = dt.date(year - 1 if allow_2016 and rng.random() < 0.03 else year, 1, 1)
    end = dt.date(year, 8, 31) if year == max(cfg.years) else dt.date(year, 12, 31)
    span = (end - start).days
    if start.year < year:
        span = 364
    vdate = start + dt.timedelta(days=int(rng.integers(0, span + 1)))
    if person is not None:
        bdate = person["bdate"]
        age_days = (vdate - bdate).days
        if age_days < 0:
            vdate = bdate + dt.timedelta(days=150)
            age_days = 150
    else:
        bdate = vdate - dt.timedelta(days=age_days)
    adult = age_days > 15 * 365
    sex = person["sex"] if person else str(rng.choice(["M", "F"]))
    pregnant = adult and sex == "F" and group == "ADULT" and rng.random() < 0.15
    delay = int(np.round(np.exp(rng.normal(1.1, 0.9))))
    ndate: dt.date | None = vdate + dt.timedelta(days=delay)
    if rng.random() < 0.005:
        ndate = vdate - dt.timedelta(days=int(rng.integers(1, 40)))
    if rng.random() < 0.0007:
        ndate = None

    # vaccines and doses
    comps = [c.strip() for c in label.replace("+", ",").split(",")]
    if label.startswith("AM-BC") and rng.random() < 0.15:
        label = label.replace("AM-BC", str(rng.choice(_AMBC_VARIANTS)), 1)
    doses = [dose] + ([str(rng.choice(["1", "2", "3", "R"]))] if len(comps) > 1 else [])

    # latent phenotype and events
    pheno_names = list(PHENOTYPES)
    pheno = str(rng.choice(pheno_names, p=PHENO_BY_GROUP[group]))
    probs_ev = dict(PHENOTYPES[pheno])
    lot_val: Any
    z_endo = 0.0
    if comps[0].upper().replace(" ", "").replace("-", "") in {"AMBC"} or "AM-BC" in comps:
        lot_id, z_endo = _choose_ambc_lot(rng, cfg.national_lots, vdate.year)
        lot_val = _lot_cell(rng, lot_id) if lot_id else None
        if len(comps) > 1:
            lot_val = f"{lot_val}, {_other_lot(rng)}"
        base = probs_ev.get("fever_39", 0.05)
        probs_ev["fever_39"] = _expit(np.log(base / (1 - base)) + cfg.endotoxin_log_or_per_sd * z_endo)
    else:
        lot_val = _other_lot(rng)
    if rng.random() < 0.0035:
        lot_val = None
    events = {k: bool(rng.random() < probs_ev.get(k, 0.0)) for k in EVENT_KEYS}
    for k, pr in RARE_SERIOUS.items():
        if rng.random() < pr:
            events[k] = True
    if events["fever_40"]:
        events["fever_39"] = True
    if not any(events.values()):
        events["other"] = True
    risk = (
        -5.2
        + 2.6 * (events["febrile_seizure"] or events["afebrile_seizure"] or events["collapse"])
        + 1.3 * events["fever_40"]
        + 2.5 * (events["anaphylactic_reaction"] or events["anaphylactic_shock"])
        + 0.9 * (age_days < 60)
        + 3.0 * any(events[k] for k in RARE_SERIOUS)
    )
    hosp = bool(rng.random() < _expit(risk))
    adm = vdate + dt.timedelta(days=int(rng.integers(0, 3))) if hosp else None
    dis = adm + dt.timedelta(days=int(rng.integers(1, 8))) if adm else None

    prov = (
        person["prov"]
        if person
        else str(
            rng.choice([c for c, _ in PROVINCES], p=np.array([w for _, w in PROVINCES]) / sum(w for _, w in PROVINCES))
        )
    )
    muni = str(rng.choice(_MUNIS[prov]))
    if rng.random() < 0.1:
        muni = muni.upper() if rng.random() < 0.5 else muni.lower() + " "
    name = person["name"] if person else (f"{rng.choice(_GIVEN)} {rng.choice(_SURN)} {rng.choice(_SURN)}")
    first_comp = comps[0].upper()
    man_key = "AM-BC" if "AM" in first_comp and "BC" in first_comp else first_comp
    man_choices = _MANUF.get(man_key, ["Finlay"])
    man: str | None = str(rng.choice(man_choices))
    if len(comps) > 1:
        other = comps[1].upper()
        man = f"{man}, {rng.choice(_MANUF.get('PENTA-L' if other.startswith('PENTA') else other, ['CIGB']))}"
    if rng.random() < 0.0077:
        man = None
    oral = first_comp == "OPV"
    site = "BOCA" if oral else ("1/3 CALM" if age_days < 3 * 365 else "DELTOIDE")
    route = "ORAL" if oral else ("SC" if first_comp in {"PRS", "AA"} else ("ID" if first_comp == "BCG" else "IM"))
    if len(comps) > 1:
        site = f"{site}, {'BOCA' if 'OPV' in label.upper() else '1/3 CALM'}"
        route = f"{route},IM"
    place = str(
        rng.choice(
            ["Vacunatorio"] * 17
            + ["vacunatorio", "Policlínico", "Punto de vacunación", "Escuela", "CMF", "VACUNATORIO "]
        )
    )
    other_text = str(rng.choice(_OTHER_TEXT)) if events["other"] else "N"
    return {
        "name": name,
        "sex": sex,
        "bdate": bdate,
        "age_days": age_days,
        "vdate": vdate,
        "ndate": ndate,
        "label": label,
        "doses": doses,
        "lot": lot_val,
        "man": man,
        "prov": prov,
        "muni": muni,
        "area": f"Policlínico {rng.choice(['Norte', 'Sur', 'Este', 'Oeste', 'Centro'])} {muni[:4]}",
        "consult": (
            None
            if rng.random() < 0.025
            else (int(rng.integers(1, 60)) if rng.random() < 0.9 else f"{int(rng.integers(1, 60))}-A")
        ),
        "address": f"{rng.choice(_STREETS)} {int(rng.integers(1, 200))} No. {int(rng.integers(1, 900))}",
        "pregnant": pregnant,
        "site": site,
        "route": route,
        "place": place,
        "events": events,
        "other_text": other_text,
        "hosp": hosp,
        "adm": adm,
        "dis": dis,
        "pheno": pheno,
        "z_endotoxin": z_endo,
        "hist": {
            k: bool(rng.random() < pr)
            for k, pr in [("pa", 0.03), ("ps", 0.01), ("pas", 0.04), ("fa", 0.05), ("fs", 0.02), ("fas", 0.06)]
        },
    }


def _row(rng: np.random.Generator, rec: dict[str, Any], dates_as_text: bool) -> list[Any]:
    sex_cell = (
        rec["sex"] if rng.random() > 0.05 else str(rng.choice([rec["sex"].lower(), rec["sex"] + " ", rec["sex"] + ","]))
    )
    age = rec["age_days"]
    ev = rec["events"]
    hist = rec["hist"]
    return [
        rec["name"],
        sex_cell,
        None if rng.random() < 0.0015 else _date_cell(rng, rec["bdate"], dates_as_text),
        _edad_text(rng, age),
        _group_text(age),
        rec["address"],
        rec["consult"],
        None if rng.random() < 0.005 else rec["area"],
        rec["muni"],
        rec["prov"] if rng.random() > 0.02 else rec["prov"].lower(),
        "S" if rec["pregnant"] else "N",
        rec["vdate"].month if rng.random() > 0.05 else rec["vdate"].month % 12 + 1,
        _date_cell(rng, rec["vdate"], dates_as_text),
        _date_cell(rng, rec["ndate"], dates_as_text),
        rec["label"],
        _dose_cell(rng, rec["doses"]),
        rec["site"],
        rec["route"],
        rec["place"],
        rec["man"],
        rec["lot"],
        _yn(rng, hist["pa"]),
        _yn(rng, hist["ps"]),
        _yn(rng, hist["pas"]),
        _yn(rng, hist["fa"]),
        _yn(rng, hist["fs"]),
        _yn(rng, hist["fas"]),
        *[_yn(rng, ev[k], 0.004) for k in EVENT_KEYS],
        rec["other_text"],
        _yn(rng, rec["hosp"], 0.0),
        _date_cell(rng, rec["adm"], dates_as_text) if rec["adm"] else "N",
        (_date_cell(rng, rec["dis"], dates_as_text) if rec["dis"] else "N") if rng.random() > 0.0008 else None,
        "S",
        _yn(rng, False, 0.0001),
        _yn(rng, False, 0.0012),
        None,
    ]


def _layout(year: int, enabled: bool) -> tuple[list[Any], dict[str, Any]]:
    """Header and layout tweaks for a given year (schema drift simulation)."""
    header = list(BASE_HEADER)
    opts: dict[str, Any] = {
        "title_row": False,
        "drop": [],
        "extra": [],
        "dates_as_text": False,
        "swap_lote_fab": False,
        "junk_value": True,
    }
    if not enabled:
        return header, opts
    if year == 2019:
        header[header.index("FABRICNATE")] = "FABRICANTE"
        opts["swap_lote_fab"] = True
    elif year == 2020:
        opts["title_row"] = True
        opts["junk_value"] = False
    elif year == 2021:
        header[header.index("PROVINCIAS")] = "PROVINCIA"
        header[header.index("CUAL (otro)")] = "CUAL"
        opts["extra"] = ["OBSERVACIONES"]
    elif year == 2022:
        header[header.index("F.VACUNACION")] = "FECHA DE VACUNACION"
        header[header.index("LLANTO PERSST.")] = "LLANTO PERSISTENTE"
    elif year == 2023:
        opts["drop"] = ["PURPURA"]
        opts["dates_as_text"] = True
    elif year == 2024:
        header[header.index("Dosis")] = "DOSIS"
        header[header.index("R.L.S")] = "RLS"
        header = [h if h is None else (h.lower() + " " if i % 3 == 0 else h) for i, h in enumerate(header)]
    elif year == 2025:
        header[header.index("FIEBRE 39")] = "FIEBRE  39"
        header[header.index("S.APLICACION")] = "S. APLICACION"
    return header, opts


def _write_year(path: Path, year: int, rows: list[list[Any]], cfg: AEFISynthConfig) -> None:
    header, opts = _layout(year, cfg.schema_variations)
    keep = [i for i, h in enumerate(BASE_HEADER) if h not in opts["drop"]]
    if opts["swap_lote_fab"]:
        a, b = BASE_HEADER.index("FABRICNATE"), BASE_HEADER.index("LOTE")
        keep[keep.index(a)], keep[keep.index(b)] = keep[keep.index(b)], keep[keep.index(a)]
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("TOTAL")
    if opts["title_row"]:
        ws.append([f"REGISTRO NACIONAL DE EVENTOS ADVERSOS {year} (SINTÉTICO)"])
    ws.append([header[i] for i in keep] + opts["extra"])
    junk_col = len(BASE_HEADER) - 1
    for k, row in enumerate(rows):
        out = [row[i] for i in keep]
        if junk_col in keep:
            out[keep.index(junk_col)] = "N" if (opts["junk_value"] and k == 3) else None
        ws.append(out + ([None] * len(opts["extra"])))
    wb.save(path)


def generate_aefi(cfg: AEFISynthConfig, out_dir: Path) -> pd.DataFrame:
    """Write one workbook per year into ``out_dir`` and return the ground-truth table."""
    rng = np.random.default_rng(cfg.seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    truth_rows: list[dict[str, Any]] = []
    persons: list[dict[str, Any]] = []
    for year in cfg.years:
        factor = {2020: 0.72, 2021: 0.68}.get(year, 1.0) * (0.65 if year == max(cfg.years) else 1.0)
        n = max(20, round(cfg.reports_per_year * cfg.scale * factor * rng.uniform(0.95, 1.05)))
        records = []
        for _ in range(n):
            person = persons[int(rng.integers(0, len(persons)))] if persons and rng.random() < 0.04 else None
            rec = _one_record(rng, year, cfg, person, allow_2016=(year == min(cfg.years)))
            if person is None and rng.random() < 0.2:
                persons.append({"name": rec["name"], "bdate": rec["bdate"], "sex": rec["sex"], "prov": rec["prov"]})
            records.append(rec)
        rows = [_row(rng, r, _layout(year, cfg.schema_variations)[1]["dates_as_text"]) for r in records]
        kinds = ["original"] * len(rows)
        # exact duplicates
        n_exact = round(len(rows) * cfg.exact_duplicate_rate)
        for i in rng.choice(len(rows), size=n_exact, replace=False):
            rows.append(list(rows[int(i)]))
            records.append(records[int(i)])
            kinds.append("exact_duplicate")
        # key duplicates: same person/date/vaccine/lot, one more event marked
        n_key = round(len(records) * cfg.key_duplicate_rate)
        ev_offset = len(BASE_HEADER) - 1 - 7 - len(EVENT_KEYS)
        for i in rng.choice(len(records) - n_exact, size=n_key, replace=False):
            dup = list(rows[int(i)])
            dup[ev_offset + EVENT_KEYS.index("persistent_crying")] = "S"
            rows.append(dup)
            records.append(records[int(i)])
            kinds.append("key_duplicate")
        order = rng.permutation(len(rows))
        rows = [rows[i] for i in order]
        records = [records[i] for i in order]
        kinds = [kinds[i] for i in order]
        _write_year(out_dir / f"EA_{year}_TOTAL.xlsx", year, rows, cfg)
        for rec, kind in zip(records, kinds, strict=True):
            truth_rows.append(
                {
                    "file_year": year,
                    "kind": kind,
                    "vaccination_date": rec["vdate"],
                    "label": rec["label"],
                    "age_days": rec["age_days"],
                    "sex": rec["sex"],
                    "pheno": rec["pheno"],
                    "hosp": rec["hosp"],
                    "z_endotoxin": rec["z_endotoxin"],
                    **{f"ev_{k}": v for k, v in rec["events"].items()},
                }
            )
    return pd.DataFrame.from_records(truth_rows)
