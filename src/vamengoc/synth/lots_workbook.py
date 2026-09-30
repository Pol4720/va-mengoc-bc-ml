"""Synthetic lot-release workbook with the layout quirks of the real file.

All values are simulated. They respect the documented specification windows
and observed ranges, include a planted process shift (for change-point
validation) and the documented defects: blank header of the counter column,
specification row under the header, duplicated lot identifiers, destination
variants and combinations, one endotoxin value typed as text with a decimal
comma, ``-`` as null, header on row 5 in the incidence sheet, lateral
cumulative block and interleaved reference rows in the coverage sheet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook

__all__ = ["LotsSynthConfig", "SyntheticLots", "generate_lots"]

LOT_HEADERS = [
    None,
    "Lote de vacuna envasada",
    "Año producción de la vacuna",
    "Destino",
    "Características organolépticas",
    "pH",
    "Concentración de proteínas",
    "Adsorción de proteínas (%)",
    "Concentración de polisacáridos",
    "Adsorción de polisacáridos (%)",
    "Concentración de Al(OH)3",
    "Concentración de tiomersal",
    "Inmunogenicidad (act. antic. bact.)",
    "Inmunogenicidad (act. antic. IgG)",
    "Esterilidad",
    "Contenido de endotoxinas (UE/mL)",
    "Contenido promedio del bulbo",
    "Identidad del polisacárido",
    "Identidad de la proteína",
    "Inocuidad",
]
SPEC_ROW = [
    None,
    None,
    None,
    None,
    "Suspensión blanco opalescente, libre de partículas extrañas",
    "6,0 - 7,2",
    "(70 -130) μg/mL",
    "≥ 80 %",
    "(70 -130) μg/mL",
    "≥ 80 %",
    "(3 - 5) mg/mL",
    "(0,07 - 0,13) mg/mL",
    "> 4",
    "≥ 7000 UIgG/mL",
    "Ausencia de crecimiento microbiano",
    "≤ 20000 UE/mL",
    "≥ 0,5 mL",
    "Cumple",
    "Cumple",
    "Satisfactoria",
]
# Irregular production volume by year (sums to 736 for the default range).
LOTS_PER_YEAR = {
    2011: 38,
    2012: 44,
    2013: 52,
    2014: 49,
    2015: 57,
    2016: 61,
    2017: 55,
    2018: 58,
    2019: 50,
    2020: 42,
    2021: 36,
    2022: 47,
    2023: 11,
    2024: 89,
    2025: 47,
}
DESTINATIONS = [
    ("Vietnam", 0.68),
    ("Nacional", 0.17),
    ("Venezuela", 0.05),
    ("Colombia", 0.03),
    ("Guatemala", 0.015),
    ("Nicaragua", 0.015),
    ("Uruguay", 0.01),
    ("Brasil", 0.01),
    ("Nacional-Colombia-Guatemala", 0.01),
    ("Bolivia", 0.01),
]
DEST_VARIANTS = {
    "Vietnam": ["Vietnam", "Vietnam ", " Vietnam", "VIETNAM", "Viet Nam"],
    "Nacional": ["Nacional", "Nacional ", "NACIONAL", "nacional"],
}


@dataclass
class LotsSynthConfig:
    seed: int = 7
    lots_per_year: dict[int, int] = field(default_factory=lambda: dict(LOTS_PER_YEAR))
    n_duplicate_ids: int = 22
    shift_year: int = 2018  # planted process shift (endotoxin down, adsorption up)
    incidence_years: tuple[int, int] = (1970, 2024)
    coverage_years: tuple[int, int] = (1986, 2025)


@dataclass
class SyntheticLots:
    lots: pd.DataFrame  # ground truth (numeric), incl. `national`
    incidence: pd.DataFrame
    coverage: pd.DataFrame
    path: Path | None = None


def _lot_ids(rng: np.random.Generator, years: list[int]) -> list[str]:
    ids = []
    counter = 101
    for y in years:
        if y <= 2014:
            lid = f"M{counter}"
        else:
            lid = f"{counter}M"
            r = rng.random()
            if r < 0.04:
                lid += "X"
            elif r < 0.06:
                lid += "x"
            elif r < 0.08:
                lid += str(rng.integers(1, 3))
        ids.append(lid)
        counter += 1
    return ids


def _simulate_lots(cfg: LotsSynthConfig, rng: np.random.Generator) -> pd.DataFrame:
    years = [y for y, n in sorted(cfg.lots_per_year.items()) for _ in range(n)]
    n = len(years)
    yr = np.array(years)
    post = (yr >= cfg.shift_year).astype(float)
    # Correlated latent process factors.
    cov = np.array([[1.0, 0.45, 0.2], [0.45, 1.0, 0.1], [0.2, 0.1, 1.0]])
    z = rng.multivariate_normal(np.zeros(3), cov, size=n)
    aloh3 = np.clip(4.0 + 0.25 * z[:, 0] + rng.normal(0, 0.1, n), 3.1, 4.8).round(2)
    prot_ads = np.clip(90 + 3 * z[:, 0] + 2.0 * post + rng.normal(0, 1.5, n), 80, 99).round(0)
    ps_ads = np.clip(91 + 3 * z[:, 1] + rng.normal(0, 2, n), 80, 100).round(0)
    prot = np.clip(100 + 9 * z[:, 2] + rng.normal(0, 4, n), 70, 130).round(0)
    ps = np.clip(98 + 8 * rng.standard_normal(n), 70, 128).round(0)
    ph = np.clip(6.5 + 0.13 * rng.standard_normal(n), 6.0, 6.9).round(1)
    thio = np.clip(0.10 + 0.009 * rng.standard_normal(n), 0.07, 0.12).round(3)
    log_endo = np.log(3500) - 0.45 * post + 0.5 * rng.standard_normal(n)
    endo = np.clip(np.exp(log_endo), 150, 19500).round(0)
    bact = 2.0 ** np.clip(np.round(7 + 1.3 * rng.standard_normal(n) + 0.3 * z[:, 2]), 3, 11)
    igg = np.clip(np.exp(np.log(19000) + 0.45 * rng.standard_normal(n) + 0.2 * z[:, 2]), 7034, 64632).round(0)
    fill = rng.uniform(0.50, 0.60, n).round(2)
    probs = np.array([p for _, p in DESTINATIONS])
    dest_idx = rng.choice(len(DESTINATIONS), size=n, p=probs / probs.sum())
    dest = [DESTINATIONS[i][0] for i in dest_idx]
    ids = _lot_ids(rng, years)
    # Duplicated identifiers: re-use earlier IDs for export lots of later years.
    dup_targets = rng.choice(np.arange(n // 2, n), size=cfg.n_duplicate_ids, replace=False)
    dup_sources = rng.choice(np.arange(0, n // 2), size=cfg.n_duplicate_ids, replace=False)
    for t, s in zip(dup_targets, dup_sources, strict=True):
        ids[t] = ids[s]
        if dest[t].startswith("Nacional"):
            dest[t] = "Vietnam"
    return pd.DataFrame(
        {
            "lot_id": ids,
            "production_year": yr,
            "destination": dest,
            "ph": ph,
            "protein_conc": prot,
            "protein_adsorption": prot_ads,
            "ps_conc": ps,
            "ps_adsorption": ps_ads,
            "aloh3_conc": aloh3,
            "thiomersal_conc": thio,
            "bactericidal_titer": bact,
            "igg_elisa": igg,
            "endotoxin": endo,
            "fill_volume": fill,
            "national": [d.startswith("Nacional") for d in dest],
        }
    )


def _simulate_incidence(cfg: LotsSynthConfig, rng: np.random.Generator) -> pd.DataFrame:
    years = np.arange(cfg.incidence_years[0], cfg.incidence_years[1] + 1)
    pop = 8.6e6 + (years - 1970) * 55_000
    pop = np.minimum(pop, 11.2e6)
    # Epidemic rise to the mid-1980s, decline after mass vaccination (1989-1991).
    rate = np.where(
        years < 1984,
        0.5 + 13.0 / (1 + np.exp(-(years - 1979) / 1.6)),
        np.where(years < 1989, 13.5 - 0.6 * (years - 1984), 0.35 + 9.0 * np.exp(-(years - 1989) / 2.2)),
    )
    rate = np.clip(rate * np.exp(rng.normal(0, 0.08, len(years))), 0.05, None)
    cases = np.round(rate * pop / 1e5).astype(int)
    cfr = np.clip(0.12 - 0.002 * (years - 1970) + rng.normal(0, 0.01, len(years)), 0.03, None)
    deaths = np.round(cases * cfr).astype(int)
    return pd.DataFrame(
        {
            "year": years,
            "cases": cases,
            "rate": np.round(cases / pop * 1e5, 1),
            "deaths": deaths,
            "death_rate": np.round(deaths / pop * 1e5, 1),
        }
    )


def _simulate_coverage(cfg: LotsSynthConfig, rng: np.random.Generator) -> pd.DataFrame:
    years = np.arange(cfg.coverage_years[0], cfg.coverage_years[1] + 1)
    doses = np.where(
        (years >= 2010) & (years <= 2024),
        np.round(rng.normal(230_000, 12_000, len(years)) - (years - 2010) * 2_500),
        np.nan,
    )
    cov = np.where(
        (years >= 1991) & (years <= 2024) & ~np.isin(years, [1997, 1999]),
        np.clip(rng.normal(98.2, 0.8, len(years)), 93, 99.9).round(1),
        np.nan,
    )
    return pd.DataFrame({"year": years, "doses": doses, "coverage": cov})


def _dest_text(rng: np.random.Generator, d: str) -> str:
    return str(rng.choice(DEST_VARIANTS[d])) if d in DEST_VARIANTS else d


def write_lots_workbook(truth: SyntheticLots, path: Path, rng: np.random.Generator) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Lotes 2009-2025"
    ws.append(LOT_HEADERS)
    ws.append(SPEC_ROW)
    lots = truth.lots
    comma_row = int(rng.integers(0, len(lots)))
    safety_dash = set(rng.choice(len(lots), size=round(len(lots) * 0.147), replace=False).tolist())
    for i, r in enumerate(lots.itertuples(index=False)):
        endo: Any = int(r.endotoxin)
        if i == comma_row:
            endo = f"{r.endotoxin:.1f}".replace(".", ",")  # decimal comma typed as text
        lot_cell: Any = r.lot_id
        ws.append(
            [
                i + 1,
                lot_cell,
                int(r.production_year),
                _dest_text(rng, r.destination),
                "Cumple",
                float(r.ph),
                int(r.protein_conc),
                int(r.protein_adsorption),
                int(r.ps_conc),
                int(r.ps_adsorption),
                float(r.aloh3_conc),
                float(r.thiomersal_conc),
                int(r.bactericidal_titer),
                float(r.igg_elisa),
                "Ausencia de crecim. microb.",
                endo,
                float(r.fill_volume),
                "Cumple",
                " Cumple" if rng.random() < 0.05 else "Cumple",
                "-" if i in safety_dash else "Satisfactoria",
            ]
        )
    ws.append([])
    ws.append([None, "Nota: datos SINTÉTICOS generados para desarrollo y pruebas."])

    inc = wb.create_sheet("Incidencia en Cuba")
    inc.append([])
    inc.append([None, "Enfermedad meningocócica. Cuba 1970-2024 (SERIE SINTÉTICA)"])
    inc.append([None, "Fuente: simulación"])
    inc.append([])
    inc.append(["Año", "Casos", "Tasa x 100 000 hab.", "Defunciones", "Tasa de defunciones x 100 000 hab.", "Fuentes"])
    for r in truth.incidence.itertuples(index=False):
        deaths: Any = int(r.deaths)
        drate: Any = float(r.death_rate)
        if r.year < 1980:
            deaths, drate = None, None
        if r.year == 2021:
            deaths, drate = "-", "-"
        src = "AnuarioEstadísticodeSaludSintético" if r.year % 7 == 0 else None
        inc.append([int(r.year), int(r.cases), float(r.rate), deaths, drate, src])
    inc.append([])
    inc.append(["Fuente: MinisteriodeSaludPública. Anuarios (texto sintético)."])

    cov = wb.create_sheet("Cobertura de vacunación")
    cov.append(["Cobertura de vacunación con VA-MENGOC-BC (SINTÉTICO)"])
    cov.append(["Año", "Dosis aplicadas", "Cobertura (%)", "Referencia"])
    for i, r in enumerate(truth.coverage.itertuples(index=False)):
        cov.append(
            [
                int(r.year),
                None if np.isnan(r.doses) else int(r.doses),
                None if np.isnan(r.coverage) else float(r.coverage),
                "MinisteriodeSaludPública.AnuarioEstadístico" if i % 5 == 0 else None,
            ]
        )
        if r.year == 2000:
            cov.append(["Referencias: DirecciónNacionaldeEstadísticas (texto sintético)"])
    cov.append([])
    cov.append(["Nota: la cobertura se calcula sobre la población diana (texto sintético)."])
    # Lateral cumulative block at L12:N19.
    cov.cell(row=12, column=12, value="Total de dosis aplicadas desde 1988")
    cum = 3_000_000
    for j, y in enumerate([1998, 2004, 2005, 2006, 2007, 2008, 2009, 2010]):
        cum += int(rng.integers(150_000, 900_000))
        cov.cell(row=13 + j, column=12, value=y)
        cov.cell(row=13 + j, column=13, value=cum)
        if y >= 2008:
            cov.cell(row=13 + j, column=14, value="provicional")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def generate_lots(cfg: LotsSynthConfig, out_dir: Path | None = None) -> SyntheticLots:
    rng = np.random.default_rng(cfg.seed)
    truth = SyntheticLots(
        lots=_simulate_lots(cfg, rng), incidence=_simulate_incidence(cfg, rng), coverage=_simulate_coverage(cfg, rng)
    )
    if out_dir is not None:
        truth.path = write_lots_workbook(truth, out_dir / "BD_para_publicación_lotes_final.xlsx", rng)
    return truth
