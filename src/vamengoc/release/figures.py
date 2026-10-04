"""Publication figures (vector PDF), in English and Spanish.

Design rules (see the dataviz method adopted for the project): one y-axis per
panel; thin marks (1.4 pt lines, ≥5 pt markers with a white ring); hairline
solid gridlines; the target vaccine in the accent blue and context in grey
(emphasis); categorical hues in a fixed validated order; text always in ink
colours, never in series colours; every figure has a table twin in the release.
Figures only ever receive disclosure-controlled, aggregated inputs.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

__all__ = ["FIGURES", "PALETTE", "apply_style", "label"]

PALETTE = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "magenta": "#e87ba4",
    "green": "#008300",
    "violet": "#4a3aa7",
    "red": "#e34948",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "surface": "#ffffff",
    "context": "#b9b7af",
    "neutral": "#f0efec",
}
SEQ_BLUE = [
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
]
CATEGORICAL = ["blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red"]
SINGLE_COL = 3.54  # 90 mm
DOUBLE_COL = 7.48  # 190 mm

LABELS: dict[str, dict[str, str]] = {
    "year": {"en": "Year", "es": "Año"},
    "month": {"en": "Month of vaccination", "es": "Mes de vacunación"},
    "reports_per_month": {"en": "Reports per month", "es": "Notificaciones por mes"},
    "rate_per_100k": {"en": "Reports per 100 000 doses", "es": "Notificaciones por 100 000 dosis"},
    "expected": {"en": "Programme reference rate", "es": "Tasa de referencia del programa"},
    "all_reports": {"en": "All vaccines", "es": "Todas las vacunas"},
    "target": {"en": "VA-MENGOC-BC", "es": "VA-MENGOC-BC"},
    "others": {"en": "Other vaccines", "es": "Otras vacunas"},
    "ror": {
        "en": "Reporting odds ratio (95% CI, log scale)",
        "es": "Razón de odds de notificación (IC 95 %, escala log)",
    },
    "primary": {"en": "All other vaccines", "es": "Todas las demás vacunas"},
    "infant": {"en": "Infant active comparator", "es": "Comparador activo en lactantes"},
    "class": {"en": "Latent class", "es": "Clase latente"},
    "item_prob": {
        "en": "Probability of the event within the class",
        "es": "Probabilidad del evento dentro de la clase",
    },
    "share": {"en": "Share of reports (%)", "es": "Proporción de notificaciones (%)"},
    "or_per_sd": {
        "en": "Odds ratio per SD of the lot attribute (95% CI)",
        "es": "Razón de odds por DE del atributo del lote (IC 95 %)",
    },
    "window": {"en": "Position in specification window", "es": "Posición en la ventana de especificación"},
    "production_year": {"en": "Production year", "es": "Año de producción"},
    "delta_auc": {
        "en": "Gain in cross-validated AUROC from QC attributes",
        "es": "Ganancia en AUROC con validación cruzada por los atributos de calidad",
    },
    "null": {"en": "Permutation null", "es": "Nulo por permutación"},
    "observed": {"en": "Observed", "es": "Observado"},
    "mde": {"en": "Minimum detectable OR", "es": "OR mínimo detectable"},
    "negative_control": {"en": "negative control", "es": "control negativo"},
    "ppk": {"en": "Ppk (95% bootstrap CI)", "es": "Ppk (IC 95 % bootstrap)"},
    "cases": {"en": "Meningococcal disease cases", "es": "Casos de enfermedad meningocócica"},
    "fitted": {"en": "Segmented NB fit", "es": "Ajuste segmentado BN"},
    "t2": {"en": "Hotelling T² (log scale)", "es": "T² de Hotelling (escala log)"},
    "limit": {"en": "99% control limit", "es": "Límite de control 99 %"},
    "mean_abs_shap": {"en": "Mean |SHAP| (log-odds)", "es": "|SHAP| medio (log-odds)"},
    "diff_window": {
        "en": "National − export (window units, 90% CI)",
        "es": "Nacional − exportación (unidades de ventana, IC 90 %)",
    },
    "margin": {"en": "Equivalence margin", "es": "Margen de equivalencia"},
    "synthetic": {"en": "SYNTHETIC DATA — NOT REAL RESULTS", "es": "DATOS SINTÉTICOS — NO SON RESULTADOS REALES"},
}


def label(key: str, lang: str) -> str:
    return LABELS[key][lang]


def apply_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "font.size": 7.5,
            "axes.titlesize": 8,
            "axes.labelsize": 7.5,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "legend.frameon": False,
            "axes.edgecolor": PALETTE["axis"],
            "axes.linewidth": 0.6,
            "axes.labelcolor": PALETTE["ink"],
            "axes.titlecolor": PALETTE["ink"],
            "text.color": PALETTE["ink"],
            "xtick.color": PALETTE["ink2"],
            "ytick.color": PALETTE["ink2"],
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 2.5,
            "ytick.major.size": 2.5,
            "axes.grid": True,
            "grid.color": PALETTE["grid"],
            "grid.linewidth": 0.5,
            "grid.linestyle": "-",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.axisbelow": True,
            "lines.linewidth": 1.4,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.02,
            "figure.dpi": 150,
            "axes.titlelocation": "left",
            "axes.titleweight": "bold",
            "svg.fonttype": "none",
        }
    )


def _watermark(fig: Figure, synthetic: bool, lang: str) -> None:
    """Diagonal 'synthetic data' mark drawn *behind* the data (transparent axes)."""
    if synthetic:
        for ax in fig.axes:
            ax.patch.set_alpha(0.0)
        fig.text(
            0.5,
            0.5,
            label("synthetic", lang),
            ha="center",
            va="center",
            rotation=25,
            fontsize=13,
            color=PALETTE["red"],
            alpha=0.16,
            weight="bold",
            zorder=-10,
        )


def _save(fig: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, metadata={"Creator": "vamengoc", "CreationDate": None, "ModDate": None})
    plt.close(fig)
    return path


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


# ---------------------------------------------------------------------------------------
# Paper 1 figures
# ---------------------------------------------------------------------------------------
def fig_rates(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    monthly_all: pd.DataFrame = data["monthly_all"]
    monthly_t: pd.DataFrame = data["monthly_target"]
    rates: pd.DataFrame = data["rates"]
    breaks: list[str] = data.get("breaks", [])
    expected: float | None = data.get("expected")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(DOUBLE_COL, 2.4), gridspec_kw={"width_ratios": [1.6, 1]})
    for df, color, key in ((monthly_all, PALETTE["context"], "all_reports"), (monthly_t, PALETTE["blue"], "target")):
        x = pd.PeriodIndex(df["month"], freq="M").to_timestamp()
        y = df["count"].map(_num)
        ax1.plot(x, y, color=color, lw=1.2, label=label(key, lang))
    for b in breaks:
        ax1.axvline(pd.Period(b, freq="M").to_timestamp(), color=PALETTE["ink2"], lw=0.6, alpha=0.6)
    ax1.set_ylabel(label("reports_per_month", lang))
    ax1.set_title("a", loc="left")
    ax1.legend(loc="upper left", ncols=2, handlelength=1.5)
    ax1.set_ylim(bottom=0)
    r = rates.dropna(subset=["rate_per_100k"])
    yr = r["year"].astype(int).to_numpy()
    rate = r["rate_per_100k"].map(_num).to_numpy()
    lo = r["rate_lo"].map(_num).to_numpy()
    hi = r["rate_hi"].map(_num).to_numpy()
    ax2.fill_between(yr, lo, hi, color=PALETTE["blue"], alpha=0.12, lw=0)
    ax2.plot(yr, rate, color=PALETTE["blue"], marker="o", ms=4.5, mec="white", mew=1.0)
    if expected:
        ax2.axhline(expected, color=PALETTE["ink2"], lw=0.8)
        ax2.annotate(
            label("expected", lang),
            (yr.min(), expected),
            xytext=(0, 3),
            textcoords="offset points",
            fontsize=6.5,
            color=PALETTE["ink2"],
        )
    ax2.set_ylabel(label("rate_per_100k", lang))
    ax2.set_xlabel(label("year", lang))
    ax2.set_title("b", loc="left")
    top = np.nanmax([np.nanmax(hi) if len(hi) else 0.0, expected or 0.0])
    ax2.set_ylim(0, top * 1.18 if top > 0 else 1)
    ax2.xaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True))
    fig.tight_layout(w_pad=2)
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_forest_disproportionality(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    df: pd.DataFrame = data["table"]
    labels_map: dict[str, dict[str, str]] = data["labels"]
    designs = [
        ("primary_all_other_vaccines", PALETTE["blue"], "primary"),
        ("infant_active_comparator", PALETTE["orange"], "infant"),
    ]
    d = df[df["design"].isin([k for k, _, _ in designs])].copy()
    d["ror_n"] = d["ror"].map(_num)
    d["a_n"] = d["a"].map(_num)
    d = d.dropna(subset=["ror_n"])
    min_a = float(data.get("min_reports", 5))
    keep_events = set(d[(d["design"] == designs[0][0]) & (d["a_n"] >= min_a)]["event"])
    d = d[d["event"].isin(keep_events)]
    events = d[d["design"] == designs[0][0]].sort_values("ror_n")["event"].tolist()
    events = [e for e in events if e in set(d["event"])]
    if not events:
        events = sorted(set(d["event"]))
    fig, ax = plt.subplots(figsize=(SINGLE_COL + 0.9, 0.24 * len(events) + 0.8))
    offs = {designs[0][0]: 0.13, designs[1][0]: -0.13}
    for key, color, lab in designs:
        s = d[d["design"] == key].set_index("event")
        ys, xs, los, his = [], [], [], []
        for i, e in enumerate(events):
            if e in s.index:
                ys.append(i + offs[key])
                xs.append(_num(s.loc[e, "ror"]))
                los.append(_num(s.loc[e, "ror_lo"]))
                his.append(_num(s.loc[e, "ror_hi"]))
        xs_a, lo_a, hi_a = np.array(xs), np.array(los), np.array(his)
        ax.errorbar(
            xs_a,
            ys,
            xerr=[xs_a - lo_a, hi_a - xs_a],
            fmt="o",
            color=color,
            ms=4,
            mec="white",
            mew=0.8,
            elinewidth=1.0,
            capsize=0,
            label=label(lab, lang),
        )
    ax.axvline(1, color=PALETTE["ink2"], lw=0.8)
    ax.set_xscale("log")
    ax.set_yticks(range(len(events)))
    ax.set_yticklabels([labels_map.get(e, {}).get(f"label_{lang}", e) for e in events])
    ax.set_xlabel(label("ror", lang))
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncols=2, handletextpad=0.3)
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_lca(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    prof: pd.DataFrame = data["profiles"]
    by_group: pd.DataFrame = data["by_group"]
    labels_map: dict[str, dict[str, str]] = data["labels"]
    items = list(dict.fromkeys(prof["item"]))
    classes = sorted(int(c) for c in prof["class"].unique())
    k = len(classes)
    mat = np.array(
        [[prof[(prof["class"] == c) & (prof["item"] == it)]["probability"].iloc[0] for it in items] for c in classes]
    )
    fig = plt.figure(figsize=(DOUBLE_COL, max(2.4, 0.22 * len(items) + 1.0)))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.35, 0.04, 0.32, 0.9], wspace=0.05)
    ax1 = fig.add_subplot(gs[0, 0])
    cax = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[0, 3])
    cmap = mpl.colors.LinearSegmentedColormap.from_list("seq", [SEQ_BLUE[0], SEQ_BLUE[6], SEQ_BLUE[-1]])
    im = ax1.imshow(mat.T, aspect="auto", cmap=cmap, vmin=0, vmax=1)
    dec = "," if lang == "es" else "."
    for i in range(mat.shape[1]):
        for j in range(mat.shape[0]):
            v = mat[j, i]
            if v >= 0.2:
                ax1.text(
                    j,
                    i,
                    f"{v:.2f}".replace(".", dec),
                    ha="center",
                    va="center",
                    fontsize=6,
                    color="white" if v > 0.55 else PALETTE["ink"],
                )
    ax1.set_xticks(range(k))
    ax1.set_xticklabels([str(c) for c in classes])
    ax1.set_yticks(range(len(items)))
    ax1.set_yticklabels([labels_map.get(it, {}).get(f"label_{lang}", it) for it in items])
    ax1.set_xlabel(label("class", lang))
    ax1.grid(False)
    ax1.set_title("a", loc="left")
    cb = fig.colorbar(im, cax=cax)
    cb.set_label(label("item_prob", lang), fontsize=6.5)
    cb.outline.set_visible(False)
    groups = [(data["target_label"], PALETTE["blue"], "target"), ("Other vaccines", PALETTE["context"], "others")]
    height = 0.36
    for gi, (g, color, key) in enumerate(groups):
        s = by_group[by_group["group"] == g].set_index("lca_class")["n"].map(_num)
        if s.empty or not np.isfinite(s.sum()) or s.sum() <= 0:
            continue
        share = 100 * s / s.sum()
        ys = np.arange(k) + (-height / 2 if gi == 0 else height / 2)
        ax2.barh(ys, [share.get(c, 0.0) for c in classes], height=height, color=color, label=label(key, lang))
    ax2.set_yticks(range(k))
    ax2.set_yticklabels([str(c) for c in classes])
    ax2.set_ylabel(label("class", lang))
    ax2.invert_yaxis()
    ax2.set_xlabel(label("share", lang))
    ax2.grid(axis="y", visible=False)
    ax2.legend(loc="lower right")
    ax2.set_title("b", loc="left")
    fig.subplots_adjust(left=0.27, right=0.98, bottom=0.14, top=0.93)
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_shap(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    imp: pd.DataFrame = data["importance"].head(12).iloc[::-1]
    names: dict[str, str] = data["names"]
    fig, ax = plt.subplots(figsize=(SINGLE_COL + 0.6, 0.2 * len(imp) + 0.7))
    ax.barh(range(len(imp)), imp["mean_abs_shap"].map(_num), color=PALETTE["blue"], height=0.55)
    ax.set_yticks(range(len(imp)))
    ax.set_yticklabels([names.get(f, f) for f in imp["feature"]])
    ax.set_xlabel(label("mean_abs_shap", lang))
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_incidence(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    inc: pd.DataFrame = data["fitted"]
    fig, ax = plt.subplots(figsize=(SINGLE_COL + 0.9, 2.1))
    ax.plot(
        inc["year"],
        inc["cases"],
        color=PALETTE["blue"],
        marker="o",
        ms=3,
        mec="white",
        mew=0.6,
        label=label("cases", lang),
    )
    ax.plot(inc["year"], inc["fitted"], color=PALETTE["ink2"], lw=0.9, label=label("fitted", lang))
    ax.axvspan(data["start"] - 0.5, data["end"] + 0.5, color=PALETTE["neutral"], lw=0)
    ax.set_yscale("log")
    ax.set_xlabel(label("year", lang))
    ax.set_ylabel(label("cases", lang))
    ax.legend(loc="upper right")
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


# ---------------------------------------------------------------------------------------
# Paper 2 figures
# ---------------------------------------------------------------------------------------
def fig_qc_annual(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    """Small multiples: annual distribution of each attribute on the window scale."""
    q: pd.DataFrame = data["quantiles"]  # attribute, production_year, q10, q25, q50, q75, q90, n
    names: dict[str, str] = data["names"]
    cps: pd.DataFrame = data["changepoints"]
    order = data.get("order") or list(dict.fromkeys(q["attribute"]))
    attrs = [a for a in order if a in set(q["attribute"])]
    sides: dict[str, str | None] = data.get("sides", {})
    ncol = 4
    nrow = math.ceil(len(attrs) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(DOUBLE_COL, 1.45 * nrow + 0.3), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).ravel()
    for ax, a in zip(axes, attrs, strict=False):
        s = q[q["attribute"] == a].sort_values("production_year")
        x = s["production_year"].astype(int)
        ax.fill_between(x, s["q10"].map(_num), s["q90"].map(_num), color=PALETTE["blue"], alpha=0.10, lw=0)
        ax.fill_between(x, s["q25"].map(_num), s["q75"].map(_num), color=PALETTE["blue"], alpha=0.22, lw=0)
        ax.plot(x, s["q50"].map(_num), color=PALETTE["blue"], lw=1.2)
        side = sides.get(a)
        for yv, is_limit in ((0, side in (None, "lower")), (1, side in (None, "upper"))):
            ax.axhline(yv, color=PALETTE["red"] if is_limit else PALETTE["axis"], lw=0.7)
        for _, c in cps[cps["attribute"] == a].iterrows():
            ax.axvline(int(c["production_year"]), color=PALETTE["ink2"], lw=0.7)
        ax.set_title(names.get(a, a), fontsize=7, weight="normal")
        ax.set_ylim(-0.1, 1.1)
    for ax in axes[len(attrs) :]:
        ax.set_visible(False)
    fig.supxlabel(label("production_year", lang), fontsize=7.5)
    fig.supylabel(label("window", lang), fontsize=7.5)
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_t2(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    q: pd.DataFrame = data["t2_quantiles"]  # production_year, q50, q90, max_below_limit_share
    limit = float(data["t2_limit"])
    fig, ax = plt.subplots(figsize=(SINGLE_COL + 0.9, 2.1))
    x = q["production_year"].astype(int)
    ax.fill_between(x, q["q25"].map(_num), q["q75"].map(_num), color=PALETTE["blue"], alpha=0.2, lw=0)
    ax.plot(x, q["q50"].map(_num), color=PALETTE["blue"], marker="o", ms=3.5, mec="white", mew=0.7)
    ax.plot(x, q["q90"].map(_num), color=PALETTE["blue"], lw=0.8, alpha=0.6)
    ax.axhline(limit, color=PALETTE["red"], lw=0.9)
    ax.annotate(
        label("limit", lang),
        (x.min(), limit),
        xytext=(0, 3),
        textcoords="offset points",
        fontsize=6.5,
        color=PALETTE["ink2"],
    )
    ax.set_yscale("log")
    ax.set_xlabel(label("production_year", lang))
    ax.set_ylabel(label("t2", lang))
    ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True))
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_forest_gee(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    g: pd.DataFrame = data["gee"]
    names: dict[str, str] = data["names"]
    outcome_names: dict[str, str] = data["outcome_names"]
    mde: dict[str, float] = data.get("mde", {})
    outcomes = list(dict.fromkeys(g["outcome"]))
    fig, axes = plt.subplots(1, len(outcomes), figsize=(DOUBLE_COL, 0.28 * g["exposure"].nunique() + 1.0), sharey=True)
    axes = np.atleast_1d(axes)
    exposures = list(dict.fromkeys(g["exposure"]))
    for ax, o in zip(axes, outcomes, strict=True):
        s = g[g["outcome"] == o].set_index("exposure")
        for i, e in enumerate(exposures):
            if e not in s.index:
                continue
            row = s.loc[e]
            neg = bool(row.get("negative_control", False))
            color = PALETTE["muted"] if neg else PALETTE["blue"]
            x, lo, hi = _num(row["or_per_sd"]), _num(row["or_lo"]), _num(row["or_hi"])
            ax.plot([lo, hi], [i, i], color=color, lw=1.1)
            ax.plot([x], [i], "o", color=color, ms=4.5, mec="white", mew=0.8)
        ax.axvline(1, color=PALETTE["ink2"], lw=0.8)
        m = mde.get(o)
        if m and np.isfinite(m):
            ax.axvspan(1 / m, m, color=PALETTE["neutral"], lw=0, zorder=0)
        ax.set_xscale("log")
        ax.set_title(outcome_names.get(o, o), fontsize=7.5, weight="normal")
        ax.grid(axis="y", visible=False)
        ticks = [0.25, 0.5, 0.7, 1.0, 1.4, 2.0, 4.0]
        lo_lim, hi_lim = ax.get_xlim()
        ax.set_xticks([t for t in ticks if lo_lim <= t <= hi_lim] or [1.0])
        ax.xaxis.set_major_formatter(
            mpl.ticker.FuncFormatter(lambda v, _p: f"{v:g}".replace(".", "," if lang == "es" else "."))
        )
        ax.xaxis.set_minor_formatter(mpl.ticker.NullFormatter())
    axes[0].set_yticks(range(len(exposures)))
    axes[0].set_yticklabels([names.get(e, e) for e in exposures])
    axes[0].invert_yaxis()
    handles = [
        Line2D([], [], color=PALETTE["blue"], marker="o", ms=4, label=label("observed", lang)),
        Line2D([], [], color=PALETTE["muted"], marker="o", ms=4, label=label("negative_control", lang)),
        Patch(facecolor=PALETTE["neutral"], edgecolor=PALETTE["axis"], linewidth=0.5, label=label("mde", lang)),
    ]
    fig.legend(handles=handles, loc="upper center", ncols=3, bbox_to_anchor=(0.5, 1.0))
    fig.supxlabel(label("or_per_sd", lang), fontsize=7.5)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_incremental(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    inc: pd.DataFrame = data["incremental"]
    outcome_names: dict[str, str] = data["outcome_names"]
    inc = inc[inc["estimable"].astype(bool)]
    fig, ax = plt.subplots(figsize=(SINGLE_COL + 0.6, 0.35 * len(inc) + 0.8))
    for i, r in enumerate(inc.itertuples(index=False)):
        ax.plot([0, _num(r.null_q95)], [i, i], color=PALETTE["context"], lw=4, solid_capstyle="butt")
        ax.plot([_num(r.delta_auc)], [i], "o", color=PALETTE["blue"], ms=5, mec="white", mew=0.8)
    ax.axvline(0, color=PALETTE["ink2"], lw=0.8)
    ax.set_yticks(range(len(inc)))
    ax.set_yticklabels([outcome_names.get(o, o) for o in inc["outcome"]])
    ax.set_xlabel(label("delta_auc", lang))
    ax.grid(axis="y", visible=False)
    handles = [
        Line2D([], [], color=PALETTE["blue"], marker="o", ls="", ms=4, label=label("observed", lang)),
        Line2D([], [], color=PALETTE["context"], lw=4, label=label("null", lang) + " (0–95 %)"),
    ]
    ax.legend(handles=handles, loc="lower right")
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_capability(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    cap: pd.DataFrame = data["capability"]
    names: dict[str, str] = data["names"]
    periods = [p for p in dict.fromkeys(cap["period"].astype(str)) if p != "all"][:2]
    attrs = list(dict.fromkeys(cap["attribute"]))
    fig, ax = plt.subplots(figsize=(SINGLE_COL + 0.9, 0.26 * len(attrs) + 0.9))
    colors = [PALETTE["blue"], PALETTE["orange"]]
    for k, p in enumerate(periods):
        s = cap[cap["period"] == p].set_index("attribute")
        off = 0.14 if k == 0 else -0.14
        for i, a in enumerate(attrs):
            if a not in s.index:
                continue
            x, lo, hi = _num(s.loc[a, "ppk"]), _num(s.loc[a, "ppk_lo"]), _num(s.loc[a, "ppk_hi"])
            ax.plot([lo, hi], [i + off] * 2, color=colors[k], lw=1.0)
            ax.plot(
                [x],
                [i + off],
                "o",
                color=colors[k],
                ms=4,
                mec="white",
                mew=0.7,
                label=p.replace("-", "\u2013") if i == 0 else None,
            )
    ax.axvline(1.33, color=PALETTE["ink2"], lw=0.8)
    ax.axvline(1.0, color=PALETTE["red"], lw=0.8)
    ax.set_yticks(range(len(attrs)))
    ax.set_yticklabels([names.get(a, a) for a in attrs])
    ax.set_xlabel(label("ppk", lang))
    ax.grid(axis="y", visible=False)
    ax.invert_yaxis()
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncols=2)
    for xv, txt in ((1.0, "1,00" if lang == "es" else "1.00"), (1.33, "1,33" if lang == "es" else "1.33")):
        ax.annotate(
            txt,
            (xv, 1.0),
            xycoords=("data", "axes fraction"),
            xytext=(2, -8),
            textcoords="offset points",
            fontsize=6.5,
            color=PALETTE["ink2"],
        )
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


def fig_equivalence(data: dict[str, Any], lang: str, path: Path, synthetic: bool) -> Path:
    eq: pd.DataFrame = data["equivalence"]
    names: dict[str, str] = data["names"]
    margin = float(data["margin"])
    fig, ax = plt.subplots(figsize=(SINGLE_COL + 0.9, 0.26 * len(eq) + 0.9))
    ax.axvspan(-margin, margin, color=PALETTE["neutral"], lw=0, zorder=0, label=label("margin", lang))
    for i, r in enumerate(eq.itertuples(index=False)):
        ax.plot([_num(r.ci90_lo), _num(r.ci90_hi)], [i, i], color=PALETTE["blue"], lw=1.1)
        ax.plot([_num(r.diff)], [i], "o", color=PALETTE["blue"], ms=4, mec="white", mew=0.7)
    ax.axvline(0, color=PALETTE["ink2"], lw=0.8)
    ax.set_yticks(range(len(eq)))
    ax.set_yticklabels([names.get(a, a) for a in eq["attribute"]])
    ax.set_xlabel(label("diff_window", lang))
    ax.grid(axis="y", visible=False)
    ax.invert_yaxis()
    ax.legend(loc="lower right")
    fig.tight_layout()
    _watermark(fig, synthetic, lang)
    return _save(fig, path)


FIGURES: dict[str, Callable[[dict[str, Any], str, Path, bool], Path]] = {
    "p1_rates": fig_rates,
    "p1_forest": fig_forest_disproportionality,
    "p1_lca": fig_lca,
    "p1_shap": fig_shap,
    "p1_incidence": fig_incidence,
    "p2_qc_annual": fig_qc_annual,
    "p2_t2": fig_t2,
    "p2_forest": fig_forest_gee,
    "p2_incremental": fig_incremental,
    "p2_capability": fig_capability,
    "p2_equivalence": fig_equivalence,
}
