"""Configuration loading.

All tunable choices of the pipeline live in versioned YAML files under
``configs/``. This module locates the project root, loads the files and exposes
them as validated, immutable objects. Nothing here touches data.
"""

from __future__ import annotations

import hashlib
import os
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "AnalysisConfig",
    "PipelineConfig",
    "Project",
    "find_project_root",
    "load_yaml",
]

_ROOT_MARKER = Path("configs") / "pipeline.yaml"


def find_project_root(start: Path | None = None) -> Path:
    """Return the repository root (the first ancestor holding ``configs/pipeline.yaml``).

    The environment variable ``VAMENGOC_HOME`` overrides the search, which lets
    the package be used from any working directory.
    """
    env = os.environ.get("VAMENGOC_HOME")
    if env:
        root = Path(env).expanduser().resolve()
        if not (root / _ROOT_MARKER).is_file():
            msg = f"VAMENGOC_HOME={root} does not contain {_ROOT_MARKER}"
            raise FileNotFoundError(msg)
        return root
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / _ROOT_MARKER).is_file():
            return candidate
    # Fall back to the source checkout that contains this module.
    pkg_root = Path(__file__).resolve().parents[2]
    if (pkg_root / _ROOT_MARKER).is_file():
        return pkg_root
    msg = "Could not locate the project root (configs/pipeline.yaml). Set VAMENGOC_HOME."
    raise FileNotFoundError(msg)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping, failing loudly on anything that is not a mapping."""
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        msg = f"{path} must contain a YAML mapping at top level"
        raise TypeError(msg)
    return data


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file, streamed."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PathsConfig(_Frozen):
    raw_dir: str
    interim_dir: str
    curated_dir: str
    synthetic_dir: str
    release_dir: str
    runs_dir: str


class InputsConfig(_Frozen):
    aefi_file_pattern: str
    aefi_preferred_sheet: str
    # Master sheet of each workbook: names matching this regex are preferred; among several
    # candidates the one with the most data rows wins (the 2021-2024 workbooks also hold
    # product sheets such as ABDALA or SOBERANA that share the AEFI layout).
    aefi_master_sheet_pattern: str = "(?i)total"
    # Sheets ingested in addition to the master sheet (e.g. 2018 "Casos que no entraron en el
    # cierre": late cases with the same layout). Their rows are deduplicated against the master.
    aefi_extra_sheet_patterns: list[str] = Field(default_factory=list)
    # Sheets never read as AEFI tables (product extracts duplicated from the master sheet).
    aefi_excluded_sheet_patterns: list[str] = Field(default_factory=list)
    lots_file_pattern: str
    sheet_patterns: dict[str, str]
    header_search_rows: int = Field(ge=1)
    min_header_matches: int = Field(ge=1)


class SecurityConfig(_Frozen):
    hmac_key_env: str
    hmac_key_file: str
    encrypt_curated: bool
    fernet_key_env: str
    fernet_key_file: str


class PlausibilityConfig(_Frozen):
    max_age_years: float
    max_notification_delay_days: int
    max_hospital_stay_days: int
    age_tolerance_months: float


class DedupConfig(_Frozen):
    key: list[str]


class DisproportionalityConfig(_Frozen):
    min_reports: int
    ror_lower_threshold: float
    prr_threshold: float
    prr_chi2_threshold: float
    ic025_threshold: float
    eb05_threshold: float
    primary_criterion: Literal["ic", "ror", "prr", "ebgm", "consensus2"] = "ic"


class LCAConfig(_Frozen):
    k_range: tuple[int, int]
    n_starts: int
    max_iter: int
    tol: float
    bootstrap: int


class SeriousnessConfig(_Frozen):
    train_years: tuple[int, int]
    test_years: tuple[int, int | None]  # null last year = latest analysed year
    n_estimators: int
    learning_rate: float
    num_leaves: int
    min_child_samples: int


class QCConfig(_Frozen):
    capability_bootstrap: int
    ewma_lambda: float = Field(gt=0, le=1)
    mspc_alpha: float = Field(gt=0, lt=1)
    changepoint_penalty: str | float
    equivalence_margin_fraction: float = Field(gt=0, lt=1)
    # Production-year periods for capability; null = lots produced before vs during the
    # pharmacovigilance study window (fixed a priori, independent of the QC data).
    capability_periods: list[tuple[int, int]] | None = None


class QCSafetyConfig(_Frozen):
    primary_outcomes: list[str]
    secondary_outcomes: list[str]
    primary_exposures: list[str]
    negative_control_exposures: list[str]
    covariates: list[str]
    gee_cov_struct: Literal["exchangeable", "independence"]
    permutation_tests: int
    cv_folds: int
    fdr_alpha: float


class LinkageConfig(_Frozen):
    fuzzy_threshold: float
    allow_fuzzy: bool
    # Shelf life of a released lot: a lot produced in year Y expires at the latest on
    # 31 December of Y + shelf_life_years. A dose recorded after that date, or before the
    # production year, cannot come from that lot (copy-paste error in the LOTE cell).
    shelf_life_years: int = Field(default=3, ge=0)
    # Candidate rules relating the lot code to its production year, checked against the lots
    # workbook (which records both). A rule is used to date lots absent from the workbook only
    # if it reproduces the recorded year for at least `code_year_min_agreement` of the lots.
    code_year_rules: list[str] = Field(
        default_factory=lambda: ["digits_first1", "digits_first2", "digits_last1", "digits_last2"]
    )
    code_year_min_agreement: float = Field(default=0.95, gt=0, le=1)
    # Shape of a VA-MENGOC-BC lot code (999A, A999, A999A, 999AA): only tokens with this shape are
    # dated from the code, so that lots of co-administered vaccines are never misread.
    target_lot_pattern: str = r"^[A-Z]?\d{3}[A-Z]{0,2}$"


class ComparatorConfig(_Frozen):
    """Paper 1 comparator (agreed with the VA-MENGOC-BC project lead).

    Other vaccines are compared only when they are products of the Finlay Vaccine Institute;
    any vaccine given in the same session is analysed as a concomitant exposure.
    """

    manufacturer: str = "FINLAY"
    # Explicit product codes; null = every vaccine whose dictionary manufacturer is `manufacturer`.
    products: list[str] | None = None


class ScheduleDose(_Frozen):
    minimum_months: float = Field(ge=0)  # below this age the dose is not valid (data error)
    routine_months: tuple[float, float]  # recommended age window [from, to)


class ScheduleConfig(_Frozen):
    """Age rules of the target vaccine in the national schedule."""

    doses: dict[str, ScheduleDose]
    max_age_years: float = Field(gt=0)  # upper age of the licensed indication
    booster_in_schedule: bool = False


class P2FeasibilityConfig(_Frozen):
    """Decision rule for Paper 2 given the share of reports whose recorded lot is impossible."""

    max_inconsistent_share: float = Field(default=0.20, gt=0, lt=1)  # above: insufficient
    caution_share: float = Field(default=0.10, gt=0, lt=1)  # above: limited (caveat)
    min_linked_reports: int = Field(default=200, ge=1)
    min_linked_lots: int = Field(default=30, ge=2)


class AnalysisConfig(_Frozen):
    seed: int
    analytic_year_from: Literal["vaccination_date", "notification_date", "file_year"]
    study_years: tuple[int, int | None]  # null last year = latest year present in the data
    target_vaccine: str
    target_manufacturer: str
    infant_comparator_max_age_months: int
    expected_national_rate_per_100k: float
    plausibility: PlausibilityConfig
    deduplication: DedupConfig
    disproportionality: DisproportionalityConfig
    lca: LCAConfig
    seriousness_model: SeriousnessConfig
    qc: QCConfig
    qc_safety: QCSafetyConfig
    linkage: LinkageConfig
    comparator: ComparatorConfig = Field(default_factory=ComparatorConfig)
    schedule: ScheduleConfig
    p2_feasibility: P2FeasibilityConfig = Field(default_factory=P2FeasibilityConfig)

    @field_validator("study_years")
    @classmethod
    def _ordered(cls, v: tuple[int, int | None]) -> tuple[int, int | None]:
        if v[1] is not None and v[0] > v[1]:
            msg = "study_years must be [first, last]"
            raise ValueError(msg)
        return v


class SDCConfig(_Frozen):
    min_cell: int = Field(ge=1)
    suppression_token: str
    secondary_suppression: bool
    round_rates_digits: int
    release_lot_values: Literal["none", "normalized", "raw"]
    release_specifications: bool = False  # absolute specification limits are industrial information
    forbidden_columns: list[str]
    forbidden_patterns: list[str]


class ReleaseConfig(_Frozen):
    origin_auto: bool
    languages: list[str]
    figure_format: str
    figure_dpi: int
    data_extraction_date: str | None = None  # ISO date of the extraction from the source database
    database_custodian: str | None = None  # institution responsible for the AEFI database


class PipelineConfig(_Frozen):
    schema_version: int
    paths: PathsConfig
    inputs: InputsConfig
    security: SecurityConfig
    analysis: AnalysisConfig
    sdc: SDCConfig
    release: ReleaseConfig


class Project:
    """A handle on the repository: root path, pipeline config and dictionaries.

    ``overrides`` is a nested mapping merged over ``configs/pipeline.yaml``;
    it is how the local lab API and the CLI customise an experiment without
    editing the versioned file (the merged result is hashed into provenance).
    """

    def __init__(self, root: Path | None = None, overrides: dict[str, Any] | None = None) -> None:
        self.root = (root or find_project_root()).resolve()
        raw = load_yaml(self.root / _ROOT_MARKER)
        if overrides:
            raw = deep_merge(raw, overrides)
        self._raw = raw
        self.config = PipelineConfig.model_validate(raw)

    # --- paths -------------------------------------------------------------
    def path(self, rel: str) -> Path:
        p = Path(rel).expanduser()
        return p if p.is_absolute() else self.root / p

    @property
    def raw_dir(self) -> Path:
        return self.path(self.config.paths.raw_dir)

    @property
    def interim_dir(self) -> Path:
        return self.path(self.config.paths.interim_dir)

    @property
    def curated_dir(self) -> Path:
        return self.path(self.config.paths.curated_dir)

    @property
    def synthetic_dir(self) -> Path:
        return self.path(self.config.paths.synthetic_dir)

    @property
    def release_dir(self) -> Path:
        return self.path(self.config.paths.release_dir)

    @property
    def runs_dir(self) -> Path:
        return self.path(self.config.paths.runs_dir)

    @property
    def configs_dir(self) -> Path:
        return self.root / "configs"

    # --- versioned dictionaries -----------------------------------------------
    @cached_property
    def aefi_schema(self) -> dict[str, Any]:
        return load_yaml(self.configs_dir / "schemas" / "aefi.yaml")

    @cached_property
    def lots_schema(self) -> dict[str, Any]:
        return load_yaml(self.configs_dir / "schemas" / "lots.yaml")

    @cached_property
    def vaccines(self) -> dict[str, Any]:
        return load_yaml(self.configs_dir / "dictionaries" / "vaccines.yaml")

    @cached_property
    def manufacturers(self) -> dict[str, Any]:
        return load_yaml(self.configs_dir / "dictionaries" / "manufacturers.yaml")

    @cached_property
    def geography(self) -> dict[str, Any]:
        return load_yaml(self.configs_dir / "dictionaries" / "geography.yaml")

    @cached_property
    def events(self) -> dict[str, Any]:
        return load_yaml(self.configs_dir / "dictionaries" / "events.yaml")

    @property
    def raw_config(self) -> dict[str, Any]:
        return self._raw

    def config_fingerprint(self) -> dict[str, str]:
        """SHA-256 of every configuration file plus the merged pipeline config."""
        out = {str(p.relative_to(self.root)): sha256_file(p) for p in sorted(self.configs_dir.rglob("*.yaml"))}
        merged = yaml.safe_dump(self._raw, sort_keys=True, allow_unicode=True).encode()
        out["<merged pipeline config>"] = hashlib.sha256(merged).hexdigest()
        return out


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base`` (override wins)."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out
