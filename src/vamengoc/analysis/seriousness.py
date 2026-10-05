"""Correlates of hospitalisation among AEFI reports.

Two complementary models on the same prespecified predictors:

* multivariable logistic regression — interpretable adjusted odds ratios, fitted with Firth's
  penalised likelihood because rare, serious event types separate the outcome (finite estimates
  under separation); predictions use the FLIC intercept correction (Puhr et al. 2017);
* gradient-boosted trees (LightGBM) — non-linearities and interactions,
  explained with exact TreeSHAP contributions (``pred_contrib``).

Performance is evaluated with *temporal* validation (train on earlier years,
test on later years), reporting discrimination (AUROC, AUPRC), calibration
(intercept and slope) and Brier score, as recommended by TRIPOD+AI. The model
is explanatory/exploratory and is not intended for clinical triage.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from vamengoc.analysis.stats_utils import drop_collinear_columns, firth_logit
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


def build_design(
    df: pd.DataFrame, min_prevalence: float = 0.002, events: list[str] | None = None
) -> tuple[pd.DataFrame, pd.Series]:
    """Predictor matrix (numeric, no missing) and binary outcome ``hospitalized``.

    ``events`` limits the event indicators used as predictors (by default every event column);
    the pipeline passes the events recorded on every form so that a change of form does not
    masquerade as a change in risk.
    """
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
    for region in ("Centro", "Oriente"):  # reference: Occidente (and unknown region)
        x[f"region_{region}"] = d["region"].eq(region).astype(int)
    for ev in events if events is not None else event_columns(d):
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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # separation on tiny test sets is reported as NaN below
        try:
            int_fit = sm.GLM(y, np.ones_like(lp), family=sm.families.Binomial(), offset=lp).fit()
            intercept = float(int_fit.params[0])
        except (ValueError, np.linalg.LinAlgError):  # pragma: no cover - degenerate
            intercept = float("nan")
        if np.std(lp) < 1e-9:
            return intercept, float("nan")  # constant predictions: slope undefined
        try:
            slope_fit = sm.GLM(y, sm.add_constant(lp, has_constant="add"), family=sm.families.Binomial()).fit()
            slope = float(slope_fit.params[1])
        except (ValueError, np.linalg.LinAlgError):  # pragma: no cover - degenerate
            slope = float("nan")
    return intercept, slope


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


def _flic_predict(xtr: pd.DataFrame, ytr: pd.Series, xte: pd.DataFrame) -> np.ndarray:
    """Firth fit on the training years with FLIC intercept correction, predicted on the test years.

    Firth's penalty biases the average predicted probability upwards for rare outcomes; FLIC
    re-estimates the intercept by maximum likelihood with the Firth linear predictor as offset.
    """
    dtr = np.column_stack([np.ones(len(xtr)), xtr.to_numpy(dtype=float)])
    kept, _ = drop_collinear_columns(dtr, ["const", *xtr.columns])
    res = firth_logit(dtr[:, kept], ytr.to_numpy(dtype=float))
    slopes = res.params[1:]
    cols = [xtr.columns[i - 1] for i in kept if i > 0]
    lp_tr = xtr[cols].to_numpy(dtype=float) @ slopes
    intercept = sm.GLM(ytr.to_numpy(dtype=float), np.ones((len(xtr), 1)), family=sm.families.Binomial(), offset=lp_tr)
    b0 = float(intercept.fit().params[0])
    lp_te = b0 + xte[cols].to_numpy(dtype=float) @ slopes
    return np.asarray(1.0 / (1.0 + np.exp(-lp_te)))


def fit_seriousness(
    df: pd.DataFrame,
    *,
    train_years: tuple[int, int],
    test_years: tuple[int, int],
    params: dict[str, Any],
    seed: int,
    events: list[str] | None = None,
) -> SeriousnessResult:
    x, y = build_design(df, events=events)
    years = df.loc[x.index, "analytic_year"].astype(int)
    tr = years.between(*train_years)
    te = years.between(*test_years)
    notes: list[str] = []
    xtr, ytr, xte, yte = x[tr], y[tr], x[te], y[te]

    # --- logistic regression (full data, interpretable) --------------------------------
    # n_events is the sum of the event indicators: exactly collinear, so it is used by the boosted
    # model only. Remaining exact collinearity is removed column by column (reported in notes).
    candidates = [c for c in x.columns if c != "n_events" and x[c].sum() >= 5]
    design = np.column_stack([np.ones(len(x)), x[candidates].to_numpy(dtype=float)])
    kept_idx, dropped = drop_collinear_columns(design, ["const", *candidates])
    keep = [candidates[i - 1] for i in kept_idx if i > 0]
    notes.extend(f"term {t} dropped from the logistic model (exact collinearity)" for t in dropped)
    try:
        res = firth_logit(design[:, kept_idx], y.to_numpy(dtype=float))
        if not res.converged:
            notes.append("Firth logistic regression did not converge")
        ci = res.conf_int()
        coef = pd.DataFrame(
            {
                "term": ["const", *keep],
                "or": np.exp(res.params),
                "or_lo": np.exp(ci[:, 0]),
                "or_hi": np.exp(ci[:, 1]),
                "p_value": res.pvalues(),
                "n_with_term": [None, *(int(x[c].sum()) if x[c].nunique() == 2 else None for c in keep)],
            }
        )
        coef = coef[coef["term"] != "const"].reset_index(drop=True)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - singular after rank check
        notes.append(f"logistic regression failed: {exc}")
        coef = pd.DataFrame(columns=["term", "or", "or_lo", "or_hi", "p_value", "n_with_term"])

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
        p_lr = _flic_predict(xtr[keep], ytr, xte[keep])
        metrics["logistic_test"] = _metrics(yte.to_numpy(), p_lr)
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
