"""Correlates of hospitalisation among AEFI reports.

Two complementary models on the same prespecified predictors:

* multivariable logistic regression — interpretable adjusted odds ratios;
* gradient-boosted trees (LightGBM) — non-linearities and interactions,
  explained with exact TreeSHAP contributions (``pred_contrib``).

Performance is evaluated with *temporal* validation (train on earlier years,
test on later years), reporting discrimination (AUROC, AUPRC), calibration
(intercept and slope) and Brier score, as recommended by TRIPOD+AI. The model
is explanatory/exploratory and is not intended for clinical triage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from vamengoc.curate.aefi_model import event_columns

__all__ = ["SeriousnessResult", "build_design", "fit_seriousness"]

TOP_VACCINES = ("PENTA-L", "AM-BC", "DPT", "HIB", "PRS", "IPV", "OPV", "HB", "AG", "TT", "DT", "AL", "BCG")


@dataclass
class SeriousnessResult:
    n_train: int
    n_test: int
    events_train: int
    events_test: int
    logistic: pd.DataFrame
    metrics: dict[str, dict[str, float]]
    shap_importance: pd.DataFrame
    shap_dependence: pd.DataFrame = field(default_factory=pd.DataFrame)
    calibration: pd.DataFrame = field(default_factory=pd.DataFrame)
    notes: list[str] = field(default_factory=list)


def build_design(df: pd.DataFrame, min_prevalence: float = 0.002) -> tuple[pd.DataFrame, pd.Series]:
    """Predictor matrix (numeric, no missing) and binary outcome ``hospitalized``."""
    d = df[df["hospitalized"].notna()].copy()
    y = d["hospitalized"].astype(bool).astype(int)
    x = pd.DataFrame(index=d.index)
    x["age_months_log"] = np.log1p(pd.to_numeric(d["age_months"], errors="coerce").astype(float))
    x["age_missing"] = x["age_months_log"].isna().astype(int)
    x["age_months_log"] = x["age_months_log"].fillna(x["age_months_log"].median())
    x["female"] = d["sex"].eq("F").astype(int)
    x["coadministered"] = d["coadministered"].astype(int)
    vac = d["vaccines"].fillna("")
    for v in TOP_VACCINES:
        x[f"vac_{v}"] = vac.str.split("|").map(lambda s, v=v: int(v in s))
    for region in ("Occidente", "Centro", "Oriente"):
        x[f"region_{region}"] = d["region"].eq(region).astype(int)
    for ev in event_columns(d):
        col = d[ev].astype("boolean").fillna(False).astype(int)
        if col.mean() >= min_prevalence:
            x[ev] = col
    x["n_events"] = d["n_events"].astype(int)
    # Drop constant columns (not estimable).
    x = x.loc[:, x.nunique() > 1]  # noqa: PD101 - column-wise constancy check on a frame
    return x, y


def _calibration(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Calibration intercept (calibration-in-the-large) and slope on the logit scale."""
    lp = np.log(np.clip(p, 1e-9, 1 - 1e-9) / (1 - np.clip(p, 1e-9, 1 - 1e-9)))
    slope_fit = sm.GLM(y, sm.add_constant(lp), family=sm.families.Binomial()).fit()
    int_fit = sm.GLM(y, np.ones_like(lp), family=sm.families.Binomial(), offset=lp).fit()
    return float(int_fit.params[0]), float(slope_fit.params[1])


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    if len(np.unique(y)) < 2:
        return {
            "auroc": float("nan"),
            "auprc": float("nan"),
            "brier": float(brier_score_loss(y, p)),
            "cal_intercept": float("nan"),
            "cal_slope": float("nan"),
            "prevalence": float(y.mean()),
        }
    ci, cs = _calibration(y, p)
    return {
        "auroc": float(roc_auc_score(y, p)),
        "auprc": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "cal_intercept": ci,
        "cal_slope": cs,
        "prevalence": float(y.mean()),
    }


def fit_seriousness(
    df: pd.DataFrame, *, train_years: tuple[int, int], test_years: tuple[int, int], params: dict[str, Any], seed: int
) -> SeriousnessResult:
    x, y = build_design(df)
    years = df.loc[x.index, "analytic_year"].astype(int)
    tr = years.between(*train_years)
    te = years.between(*test_years)
    notes: list[str] = []
    xtr, ytr, xte, yte = x[tr], y[tr], x[te], y[te]

    # --- logistic regression (full data, interpretable) --------------------------------
    keep = [c for c in x.columns if x[c].sum() >= 5]
    logit = sm.GLM(y, sm.add_constant(x[keep].astype(float)), family=sm.families.Binomial())
    try:
        res = logit.fit()
        ci = res.conf_int()
        coef = pd.DataFrame(
            {
                "term": res.params.index,
                "or": np.exp(res.params.to_numpy()),
                "or_lo": np.exp(ci[0].to_numpy()),
                "or_hi": np.exp(ci[1].to_numpy()),
                "p_value": res.pvalues.to_numpy(),
            }
        )
        coef = coef[coef["term"] != "const"].reset_index(drop=True)
    except (np.linalg.LinAlgError, ValueError) as exc:  # pragma: no cover - separation
        notes.append(f"logistic regression failed: {exc}")
        coef = pd.DataFrame(columns=["term", "or", "or_lo", "or_hi", "p_value"])

    # --- gradient boosting with temporal validation -------------------------------------
    lgb_params: dict[str, Any] = {
        "objective": "binary",
        "n_estimators": int(params["n_estimators"]),
        "learning_rate": float(params["learning_rate"]),
        "num_leaves": int(params["num_leaves"]),
        "min_child_samples": int(params["min_child_samples"]),
        "subsample": 0.8,
        "subsample_freq": 1,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
        "random_state": seed,
        "deterministic": True,
        "force_row_wise": True,
        "n_jobs": 1,
        "verbose": -1,
    }
    metrics: dict[str, dict[str, float]] = {}
    shap_imp = pd.DataFrame(columns=["feature", "mean_abs_shap"])
    dep = pd.DataFrame()
    calib = pd.DataFrame()
    if ytr.sum() >= 10 and yte.sum() >= 5:
        model = lgb.LGBMClassifier(**lgb_params)
        model.fit(xtr, ytr)
        p_te = np.asarray(model.predict_proba(xte))[:, 1]
        metrics["gbm_test"] = _metrics(yte.to_numpy(), p_te)
        lr_tr = sm.GLM(
            ytr, sm.add_constant(xtr[keep].astype(float), has_constant="add"), family=sm.families.Binomial()
        ).fit()
        p_lr = lr_tr.predict(sm.add_constant(xte[keep].astype(float), has_constant="add"))
        metrics["logistic_test"] = _metrics(yte.to_numpy(), np.asarray(p_lr))
        contrib = np.asarray(model.booster_.predict(xte, pred_contrib=True))
        sv = pd.DataFrame(contrib[:, :-1], columns=x.columns, index=xte.index)
        shap_imp = (
            sv.abs()
            .mean()
            .rename("mean_abs_shap")
            .sort_values(ascending=False)
            .reset_index()
            .rename(columns={"index": "feature"})
        )
        # binned dependence for the top continuous-like features (aggregated, disclosure-safe)
        rows = []
        for feat in shap_imp["feature"].head(8):
            vals = xte[feat]
            if vals.nunique() <= 2:
                for level in sorted(vals.unique()):
                    m = vals == level
                    rows.append(
                        {
                            "feature": feat,
                            "bin": str(level),
                            "n": int(m.sum()),
                            "mean_shap": float(sv.loc[m, feat].mean()),
                        }
                    )
            else:
                bins = pd.qcut(vals, q=min(10, vals.nunique()), duplicates="drop")
                for b, g in sv[feat].groupby(bins, observed=True):
                    rows.append({"feature": feat, "bin": str(b), "n": len(g), "mean_shap": float(g.mean())})
        dep = pd.DataFrame.from_records(rows)
        # calibration by decile (aggregated)
        q = pd.qcut(pd.Series(p_te, index=xte.index), q=10, duplicates="drop")
        calib = (
            pd.DataFrame({"p": p_te, "y": yte.to_numpy(), "bin": q.to_numpy()})
            .groupby("bin", observed=True)
            .agg(n=("y", "size"), observed=("y", "mean"), predicted=("p", "mean"))
            .reset_index(drop=True)
        )
    else:
        notes.append("too few hospitalisations for temporal validation of the boosted model")
    return SeriousnessResult(
        n_train=int(tr.sum()),
        n_test=int(te.sum()),
        events_train=int(ytr.sum()),
        events_test=int(yte.sum()),
        logistic=coef,
        metrics=metrics,
        shap_importance=shap_imp,
        shap_dependence=dep,
        calibration=calib,
        notes=notes,
    )
