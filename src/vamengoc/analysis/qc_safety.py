"""Quality-to-safety linkage: are lot-release attributes associated with the
profile of AEFI reported after VA-MENGOC-BC?

Design. Doses administered per lot are unknown, so absolute risks per lot
cannot be estimated. The analysis is a *case-only* (report-level) design:
among AEFI reports linked to a lot, it asks whether the probability that a
report includes a given event (e.g. fever ≥39 °C) varies with the lot's
quality attributes. This is valid for the *relative* event profile under the
assumption that reporting completeness does not differ by event type across
lots in a way related to the attributes (stated as a limitation).

Estimators:

* GEE logistic regression, exchangeable working correlation within lot,
  robust (sandwich) standard errors — one model per outcome × exposure plus
  a mutually adjusted model; Benjamini–Hochberg FDR over the family;
* Bayesian mixed logistic model (random lot intercept, variational Bayes) as
  a sensitivity analysis;
* lot-level quasi-binomial model of the event proportion;
* an incremental-information test: gradient boosting with lot-grouped
  cross-validation, comparing AUROC with and without QC attributes; the null
  distribution permutes QC profiles *between lots*;
* the minimum detectable odds ratio given the number of lots, reports per
  lot and intra-lot correlation (design effect), to interpret null findings.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM

from vamengoc.analysis.spc import AttributeScale, transform_values
from vamengoc.analysis.stats_utils import benjamini_hochberg
from vamengoc.curate.aefi_model import recorded_mask

__all__ = [
    "QCSafetyFrame",
    "build_qc_safety_frame",
    "gee_family",
    "incremental_value",
    "lot_level_models",
    "minimum_detectable_or",
    "mixed_model_sensitivity",
]


@dataclass
class QCSafetyFrame:
    data: pd.DataFrame  # one row per linked report
    exposures: list[str]  # standardised exposure columns (z_*)
    exposure_sd: dict[str, float]  # SD (analysis scale) used for standardisation
    covariate_terms: list[str]
    n_lots: int
    notes: list[str] = field(default_factory=list)
    # Event columns present in each source file; outcomes are analysed only where recorded.
    recorded_events: dict[str, list[str]] = field(default_factory=dict)

    def rows_for(self, outcome: str) -> pd.DataFrame:
        """Reports whose notification form recorded ``outcome``."""
        return self.data[recorded_mask(self.data, outcome, self.recorded_events)]


def build_qc_safety_frame(
    reports: pd.DataFrame,
    links: pd.DataFrame,
    lots: pd.DataFrame,
    scales: dict[str, AttributeScale],
    exposures: list[str],
    atypicality: pd.Series | None = None,
    *,
    restrict_levels: tuple[str, ...] = ("exact", "core", "fuzzy"),
    drop_temporal_implausible: bool = True,
    exclude_coadministered: bool = False,
    recorded_events: dict[str, list[str]] | None = None,
) -> QCSafetyFrame:
    notes: list[str] = []
    lk = links[links["lot_key"].notna() & links["match_level"].isin(restrict_levels)].copy()
    if drop_temporal_implausible:
        lk = lk[lk["temporal_ok"] != False]  # noqa: E712 - keep None (unknown) and True
    d = reports.merge(lk[["record_id", "lot_key", "match_level"]], on="record_id", how="inner")
    if exclude_coadministered:
        d = d[~d["coadministered"]]
    lot_attrs = lots.set_index("lot_key")
    exp_cols: list[str] = []
    sd_map: dict[str, float] = {}
    used_lots = d["lot_key"].unique()
    for e in exposures:
        if e == "atypicality_t2":
            if atypicality is None:
                continue
            vals = atypicality.reindex(used_lots).astype(float)
            tr_vals = np.log1p(vals)
        else:
            if e not in lot_attrs or e not in scales:
                notes.append(f"exposure {e} unavailable")
                continue
            tr_vals = pd.Series(
                transform_values(lot_attrs.loc[used_lots, e].to_numpy(dtype=float), scales[e].transform),
                index=used_lots,
            )
        sd = float(np.nanstd(tr_vals.to_numpy(dtype=float), ddof=1))
        mu = float(np.nanmean(tr_vals.to_numpy(dtype=float)))
        if not np.isfinite(sd) or sd <= 0:
            notes.append(f"exposure {e} has no between-lot variation")
            continue
        col = f"z_{e}"
        d[col] = d["lot_key"].map((tr_vals - mu) / sd)
        exp_cols.append(col)
        sd_map[e] = sd
    d["log_age_months"] = np.log1p(pd.to_numeric(d["age_months"], errors="coerce").astype(float))
    d["female"] = d["sex"].eq("F").astype(float)
    d["dose2"] = d["target_dose_number"].astype("Float64").eq(2).fillna(False).astype(float)
    d["dose_other"] = (~d["target_dose_number"].astype("Float64").isin([1, 2]).fillna(False)).astype(float)
    d["coadm"] = d["coadministered"].astype(float)
    d["year_c"] = d["analytic_year"].astype(float) - float(d["analytic_year"].astype(float).min())
    d["year_f"] = d["analytic_year"].astype(int).astype(str)
    d = d.dropna(subset=["log_age_months", *exp_cols])
    cov_terms = ["log_age_months", "female", "dose2", "dose_other", "C(year_f)"]
    if not exclude_coadministered and not (d["coadm"] == d["coadm"].iloc[0]).all():
        cov_terms.append("coadm")
    for c in ("dose2", "dose_other", "female"):
        if d[c].nunique() < 2:
            cov_terms.remove(c)
    if d["year_f"].nunique() < 2:
        cov_terms.remove("C(year_f)")
    cov_terms, dropped = _drop_collinear(d, cov_terms, exp_cols)
    notes.extend(f"covariate {t} dropped (collinear with the rest of the design)" for t in dropped)
    return QCSafetyFrame(
        data=d.reset_index(drop=True),
        exposures=exp_cols,
        exposure_sd=sd_map,
        covariate_terms=cov_terms,
        n_lots=int(d["lot_key"].nunique()),
        notes=notes,
        recorded_events=dict(recorded_events or {}),
    )


def _design(d: pd.DataFrame, terms: list[str]) -> np.ndarray:
    cols = []
    for t in terms:
        if t.startswith("C("):
            var = t[2:-1]
            dummies = pd.get_dummies(d[var], drop_first=True, dtype=float)
            cols.append(dummies.to_numpy())
        else:
            cols.append(d[[t]].to_numpy(dtype=float))
    return np.hstack([np.ones((len(d), 1)), *cols]) if cols else np.ones((len(d), 1))


def _drop_collinear(d: pd.DataFrame, cov_terms: list[str], exposures: list[str]) -> tuple[list[str], list[str]]:
    """Remove covariates (last first) until [1, covariates, exposures] has full column rank."""
    terms = list(cov_terms)
    dropped: list[str] = []
    while terms:
        x = _design(d, [*terms, *exposures])
        if np.linalg.matrix_rank(x) == x.shape[1]:
            break
        # find the covariate whose removal restores the most rank, scanning from the end
        for t in reversed(terms):
            trial = [u for u in terms if u != t]
            xt = _design(d, [*trial, *exposures])
            if np.linalg.matrix_rank(xt) == xt.shape[1]:
                terms.remove(t)
                dropped.append(t)
                break
        else:
            dropped.append(terms.pop())
    return terms, dropped


def _outcome(d: pd.DataFrame, outcome: str) -> pd.Series:
    return d[outcome].astype("boolean").fillna(False).astype(float)


def _fit_gee(d: pd.DataFrame, formula: str, cov_struct: str) -> Any:
    """GEE logistic model clustered by lot.

    ``exchangeable`` uses statsmodels' GEE; ``independence`` is fitted as a GLM
    with cluster-robust (sandwich) covariance, which is the same estimator and
    much faster.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if cov_struct == "exchangeable":
            model = smf.gee(
                formula,
                groups="lot_key",
                data=d,
                family=sm.families.Binomial(),
                cov_struct=sm.cov_struct.Exchangeable(),
            )
            res = model.fit(maxiter=200)
            res.working_corr = float(np.asarray(res.cov_struct.dep_params).ravel()[0])
        else:
            groups = pd.factorize(d["lot_key"])[0]
            res = smf.glm(formula, data=d, family=sm.families.Binomial()).fit(
                cov_type="cluster", cov_kwds={"groups": groups}
            )
            res.working_corr = 0.0
    res.caught_warnings = [str(w.message) for w in caught]
    return res


def gee_family(
    frame: QCSafetyFrame,
    outcomes: list[str],
    *,
    cov_struct: str = "exchangeable",
    negative_controls: list[str] | None = None,
    adjust_set: list[str] | None = None,
    crude: bool = False,
) -> pd.DataFrame:
    """Single-exposure models for every exposure and a mutually adjusted model.

    The mutually adjusted model includes only ``adjust_set`` (the prespecified
    primary exposures); by default every non-negative-control exposure. With
    ``crude=True``, unadjusted single-exposure models (``model == "crude"``) are
    added for reporting (STROBE item 16a); they are outside the FDR family.
    """
    rows: list[dict[str, Any]] = []
    neg = {f"z_{e}" for e in (negative_controls or [])}
    covs = " + ".join(frame.covariate_terms) if frame.covariate_terms else "1"
    for outcome in outcomes:
        d = frame.rows_for(outcome).copy()
        d["_y"] = _outcome(d, outcome)
        n_events = int(d["_y"].sum())
        if n_events < 10 or n_events > len(d) - 10:
            rows.append(
                {
                    "outcome": outcome,
                    "exposure": None,
                    "model": "skipped",
                    "n": len(d),
                    "n_events": n_events,
                    "note": "too few events or non-events",
                }
            )
            continue
        specs = [(e, f"_y ~ {e} + {covs}", "single") for e in frame.exposures]
        if crude:
            specs += [(e, f"_y ~ {e}", "crude") for e in frame.exposures]
        primary = [
            e for e in frame.exposures if e not in neg and (adjust_set is None or e.removeprefix("z_") in adjust_set)
        ]
        if len(primary) > 1:
            specs.append(("+".join(primary), f"_y ~ {' + '.join(primary)} + {covs}", "mutually_adjusted"))
        for label, formula, kind in specs:
            try:
                res = _fit_gee(d, formula, cov_struct)
            except (np.linalg.LinAlgError, ValueError) as exc:  # pragma: no cover - degenerate design
                rows.append(
                    {
                        "outcome": outcome,
                        "exposure": label,
                        "model": kind,
                        "n": len(d),
                        "n_events": n_events,
                        "note": f"failed: {exc}",
                    }
                )
                continue
            terms = label.split("+") if kind == "mutually_adjusted" else [label]
            # A non-positive robust variance (sparse outcome) yields NaN standard errors: such models
            # are reported as not estimable below, so numpy's sqrt warning is not useful output.
            with np.errstate(invalid="ignore"):
                ci = res.conf_int()
                bse = np.asarray(res.bse, dtype=float)
            if not np.all(np.isfinite(res.params)) or not np.all(np.isfinite(bse)):
                rows.append(
                    {
                        "outcome": outcome,
                        "exposure": label,
                        "model": kind,
                        "n": len(d),
                        "n_events": n_events,
                        "note": "non-convergent (non-finite estimates)",
                    }
                )
                continue
            for term in terms:
                b = float(res.params[term])
                rows.append(
                    {
                        "outcome": outcome,
                        "exposure": term.removeprefix("z_"),
                        "model": kind,
                        "negative_control": term in neg,
                        "n": int(res.nobs),
                        "n_events": n_events,
                        "n_lots": int(d["lot_key"].nunique()),
                        "or_per_sd": math.exp(b),
                        "or_lo": math.exp(float(ci.loc[term, 0])),
                        "or_hi": math.exp(float(ci.loc[term, 1])),
                        "p_value": float(res.pvalues[term]),
                        "working_corr": res.working_corr,
                        "note": "; ".join(sorted(set(res.caught_warnings)))[:300],
                    }
                )
    out = pd.DataFrame.from_records(rows)
    if "p_value" in out:
        negc = (
            out["negative_control"].astype("boolean").fillna(False).astype(bool)
            if "negative_control" in out
            else pd.Series(False, index=out.index)
        )
        fam = (out["model"] == "single") & ~negc & out["p_value"].notna()
        out["p_bh"] = np.nan
        out.loc[fam, "p_bh"] = benjamini_hochberg(out.loc[fam, "p_value"].to_numpy())
    return out


def mixed_model_sensitivity(frame: QCSafetyFrame, outcomes: list[str]) -> pd.DataFrame:
    """Random-intercept logistic model (variational Bayes) with all primary exposures."""
    rows = []
    fixed = [t for t in frame.covariate_terms if not t.startswith("C(")] + frame.exposures
    for outcome in outcomes:
        d = frame.rows_for(outcome).copy()
        d["_y"] = _outcome(d, outcome)
        if d["_y"].sum() < 10:
            continue
        formula = "_y ~ " + " + ".join([*fixed, "year_c"])
        model = BinomialBayesMixedGLM.from_formula(formula, {"lot": "0 + C(lot_key)"}, d)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            res = model.fit_vb()
        names = model.exog_names
        for e in frame.exposures:
            j = names.index(e)
            m, s = float(res.fe_mean[j]), float(res.fe_sd[j])
            rows.append(
                {
                    "outcome": outcome,
                    "exposure": e.removeprefix("z_"),
                    "or_per_sd": math.exp(m),
                    "cri_lo": math.exp(m - 1.96 * s),
                    "cri_hi": math.exp(m + 1.96 * s),
                    "lot_sd": float(np.exp(res.vcp_mean[0])),
                }
            )
    return pd.DataFrame.from_records(rows)


def lot_level_models(frame: QCSafetyFrame, outcomes: list[str], min_reports: int = 5) -> pd.DataFrame:
    """Quasi-binomial GLM of the per-lot event proportion on each standardised exposure."""
    rows = []
    for outcome in outcomes:
        d = frame.rows_for(outcome)
        y = _outcome(d, outcome)
        agg = (
            d.assign(_y=y)
            .groupby("lot_key")
            .agg(
                events=("_y", "sum"),
                n=("_y", "size"),
                year=("year_c", "mean"),
                **{e: (e, "first") for e in frame.exposures},
            )
        )
        agg = agg[agg["n"] >= min_reports]
        if len(agg) < 10 or agg["events"].sum() == 0:
            continue
        # Proportions with var_weights = n: the Pearson dispersion is then on the count scale.
        # (With a two-column endog, statsmodels' scale="X2" is computed on the proportion scale and
        # underestimates the dispersion by a factor of about the mean lot size.)
        prop = (agg["events"] / agg["n"]).astype(float)
        for e in frame.exposures:
            x = sm.add_constant(agg[[e, "year"]].astype(float))
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                res = sm.GLM(prop, x, family=sm.families.Binomial(), var_weights=agg["n"].astype(float)).fit(scale="X2")
            ci = res.conf_int()
            rows.append(
                {
                    "outcome": outcome,
                    "exposure": e.removeprefix("z_"),
                    "n_lots": len(agg),
                    "or_per_sd": math.exp(res.params[e]),
                    "or_lo": math.exp(ci.loc[e, 0]),
                    "or_hi": math.exp(ci.loc[e, 1]),
                    "p_value": float(res.pvalues[e]),
                    "dispersion": float(res.scale),
                }
            )
    return pd.DataFrame.from_records(rows)


def icc_anova(y: pd.Series, groups: pd.Series) -> float:
    """ANOVA estimator of the intra-cluster correlation of a binary outcome."""
    df = pd.DataFrame({"y": y.astype(float), "g": groups})
    k = df["g"].nunique()
    n = len(df)
    if k < 2 or n <= k:
        return 0.0
    sizes = df.groupby("g").size()
    n0 = (n - (sizes**2).sum() / n) / (k - 1)
    grand = df["y"].mean()
    means = df.groupby("g")["y"].mean()
    msb = float((sizes * (means - grand) ** 2).sum() / (k - 1))
    msw = float(((df["y"] - df["g"].map(means)) ** 2).sum() / (n - k))
    denom = msb + (n0 - 1) * msw
    return max(0.0, (msb - msw) / denom) if denom > 0 else 0.0


def minimum_detectable_or(
    frame: QCSafetyFrame, outcome: str, *, alpha: float = 0.05, power: float = 0.8, r2_exposure: float = 0.2
) -> dict[str, float]:
    """Smallest OR per SD detectable given clustering (Hsieh 1989 with a design effect).

    ``r2_exposure`` is the share of exposure variance explained by covariates
    (variance-inflation factor 1/(1 − R²)).
    """
    d = frame.rows_for(outcome)
    y = _outcome(d, outcome)
    p = float(y.mean())
    icc = icc_anova(y, d["lot_key"])
    sizes = d.groupby("lot_key").size()
    m_bar = float((sizes**2).sum() / sizes.sum())  # size-weighted mean cluster size
    deff = 1 + (m_bar - 1) * icc
    # Exposure is lot-level: the effective sample for its coefficient is bounded by clustering.
    n_eff = len(d) / deff
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    if p <= 0 or p >= 1:
        return {"outcome_prevalence": p, "icc": icc, "design_effect": deff, "mde_or_per_sd": math.nan}
    log_or = z / math.sqrt(n_eff * p * (1 - p) * (1 - r2_exposure))
    return {
        "outcome_prevalence": p,
        "icc": icc,
        "mean_cluster_size": m_bar,
        "design_effect": deff,
        "n_effective": n_eff,
        "mde_or_per_sd": math.exp(log_or),
        "n_lots": float(frame.n_lots),
    }


def incremental_value(
    frame: QCSafetyFrame, outcome: str, *, folds: int = 5, n_perm: int = 200, seed: int = 0
) -> dict[str, Any]:
    """Does adding lot QC attributes improve out-of-lot prediction of the event?

    AUROC is estimated with GroupKFold by lot. The permutation null shuffles
    complete QC profiles among lots (preserving within-lot structure and the
    joint distribution of attributes).
    """
    d = frame.rows_for(outcome)
    y = _outcome(d, outcome).to_numpy()
    if not frame.exposures or y.sum() < 20 or (len(y) - y.sum()) < 20 or frame.n_lots < folds:
        return {"outcome": outcome, "estimable": False}
    base = d[["log_age_months", "female", "dose2", "dose_other", "coadm", "year_c"]].to_numpy(dtype=float)
    qc = d[frame.exposures].to_numpy(dtype=float)
    groups = d["lot_key"].to_numpy()
    gkf = GroupKFold(n_splits=folds)
    splits = list(gkf.split(base, y, groups))
    params: dict[str, Any] = {
        "objective": "binary",
        "n_estimators": 150,
        "learning_rate": 0.05,
        "num_leaves": 7,
        "min_child_samples": 40,
        "subsample": 0.8,
        "subsample_freq": 1,
        "reg_lambda": 5.0,
        "random_state": seed,
        "deterministic": True,
        "force_row_wise": True,
        "n_jobs": 1,
        "verbose": -1,
    }

    def cv_auc(x: np.ndarray) -> float:
        pred = np.zeros(len(y))
        for tr, te in splits:
            m = lgb.LGBMClassifier(**params)
            m.fit(x[tr], y[tr])
            pred[te] = np.asarray(m.predict_proba(x[te]))[:, 1]
        return float(roc_auc_score(y, pred))

    auc_base = cv_auc(base)
    auc_full = cv_auc(np.hstack([base, qc]))
    delta = auc_full - auc_base
    rng = np.random.default_rng(seed)
    lot_ids = pd.unique(groups)
    lot_profile = pd.DataFrame(qc, index=groups).groupby(level=0).first()
    null = []
    for _ in range(n_perm):
        perm = rng.permutation(lot_ids)
        mapping = dict(zip(lot_ids, perm, strict=True))
        qc_perm = lot_profile.loc[[mapping[g] for g in groups]].to_numpy()
        null.append(cv_auc(np.hstack([base, qc_perm])) - auc_base)
    null_arr = np.asarray(null)
    p = float((np.sum(null_arr >= delta) + 1) / (len(null_arr) + 1)) if n_perm else math.nan
    return {
        "outcome": outcome,
        "estimable": True,
        "auc_base": auc_base,
        "auc_with_qc": auc_full,
        "delta_auc": delta,
        "perm_p": p,
        "n_perm": n_perm,
        "null_q95": float(np.quantile(null_arr, 0.95)) if n_perm else math.nan,
        "n_reports": len(y),
        "n_lots": frame.n_lots,
        "folds": folds,
    }
