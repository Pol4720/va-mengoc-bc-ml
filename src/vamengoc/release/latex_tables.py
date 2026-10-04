"""Complete LaTeX tables generated from the released (disclosure-controlled) tables.

Each table is emitted as a macro holding a full ``tabular`` so manuscripts never contain
hand-typed results. Headers and row labels are bilingual through ``\\VLang{en}{es}`` (defined
by the manuscript preamble) and every number goes through ``siunitx`` so the decimal marker
follows the document language. Only released values are used, so a table can never show more
than the public CSV files.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from vamengoc.release.macros import format_p, latex_text, macro_name
from vamengoc.release.sdc import SECONDARY_TOKEN

__all__ = ["TableSet"]

Lang = tuple[str, str]

CHAR_VARIABLES: list[tuple[str, Lang, list[tuple[str, Lang]]]] = [
    ("sex", ("Sex", "Sexo"), [("F", ("Female", "Femenino")), ("M", ("Male", "Masculino"))]),
    (
        "age_band",
        ("Age", "Edad"),
        [
            ("0-2m", ("≤2 months", "≤2 meses")),
            ("2-4m", (">2–4 months", ">2–4 meses")),
            ("4-6m", (">4–6 months", ">4–6 meses")),
            ("6-11m", (">6–12 months", ">6–12 meses")),
            ("12-23m", (">12–24 months", ">12–24 meses")),
            ("2-5y", (">2–6 years", ">2–6 años")),
            ("6-14y", (">6–15 years", ">6–15 años")),
            ("15-60y", (">15–61 years", ">15–61 años")),
            ("61y+", (">61 years", ">61 años")),
        ],
    ),
    (
        "region",
        ("Region", "Región"),
        [
            ("Occidente", ("Western", "Occidente")),
            ("Centro", ("Central", "Centro")),
            ("Oriente", ("Eastern", "Oriente")),
        ],
    ),
    (
        "place",
        ("Place of vaccination", "Lugar de vacunación"),
        [
            ("VACCINATION_ROOM", ("Vaccination room", "Vacunatorio")),
            ("POLYCLINIC", ("Polyclinic", "Policlínico")),
            ("FAMILY_DOCTOR", ("Family doctor's office", "Consultorio del médico de familia")),
            ("SCHOOL", ("School or day care", "Escuela o círculo infantil")),
            ("VACCINATION_POST", ("Vaccination post", "Puesto de vacunación")),
            ("HOSPITAL", ("Hospital or maternity", "Hospital o maternidad")),
            ("WORKPLACE", ("Workplace or other institution", "Centro de trabajo u otra institución")),
            ("HOME", ("Home visit", "Visita domiciliaria")),
        ],
    ),
    (
        "dose",
        ("Dose", "Dosis"),
        [
            ("1", ("First", "Primera")),
            ("2", ("Second", "Segunda")),
            ("3", ("Third", "Tercera")),
            ("R", ("Booster", "Reactivación")),
            ("U", ("Single dose", "Dosis única")),
            ("multiple", ("Several vaccines with doses", "Varias vacunas con dosis")),
            ("other", ("Other", "Otra")),
        ],
    ),
    ("coadministered", ("Co-administered vaccines", "Vacunas coadministradas"), [("Yes", ("Yes", "Sí"))]),
    ("hospitalized", ("Hospitalised", "Hospitalizado"), [("Yes", ("Yes", "Sí"))]),
    ("any_serious_event", ("Serious event reported", "Evento grave notificado"), [("Yes", ("Yes", "Sí"))]),
    ("pregnant", ("Pregnant", "Embarazada"), [("Yes", ("Yes", "Sí"))]),
]
MISSING: Lang = ("Not recorded", "No registrado")
TO = "\\VLang{to}{a}"  # interval separator safe for negative bounds
FIRST = ">{{\\raggedright\\arraybackslash}}p{{{}}}"  # wrapping first column of a given width
DESIGNS: dict[str, Lang] = {
    "primary_all_other_vaccines": ("Primary: all other vaccines", "Principal: resto de vacunas"),
    "infant_active_comparator": ("Infants <12 months, active comparator", "Lactantes <12 meses, comparador activo"),
    "excluding_coadministration": ("Single-vaccine reports only", "Solo notificaciones de una vacuna"),
    "excluding_pentavalent_masking": (
        "Comparator without PENTA-L reports (masking)",
        "Comparador sin notificaciones de PENTA-L (enmascaramiento)",
    ),
}
SENSITIVITY: dict[str, Lang] = {
    "exact_links_only": ("Exact lot|links only", "Solo enlaces|exactos"),
    "excluding_coadministration": ("Excluding co-|administration", "Excluyendo|coadministración"),
    "keeping_temporally_implausible": ("Keeping implausible|dates", "Conservando fechas|inverosímiles"),
}


def vl(en: str, es: str) -> str:
    """Bilingual text as ``\\VLang{en}{es}`` (both LaTeX-escaped)."""
    return f"\\VLang{{{latex_text(en)}}}{{{latex_text(es)}}}"


def hd(en: str, es: str) -> str:
    """Bilingual header cell; ``|`` marks a line break (``\\makecell``)."""
    return (
        "\\makecell{\\VLang{"
        + "\\\\".join(latex_text(x) for x in en.split("|"))
        + "}{"
        + "\\\\".join(latex_text(x) for x in es.split("|"))
        + "}}"
    )


def _is_suppressed(v: Any, token: str) -> bool:
    return isinstance(v, str) and v == token


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def num(v: Any, digits: int = 0, token: str = "<5") -> str:  # noqa: S107 - disclosure token
    if isinstance(v, str) and v == SECONDARY_TOKEN:
        return "[c]"
    if _is_suppressed(v, token):
        return "\\ensuremath{<}\\num{" + token.lstrip("<") + "}"
    f = _float(v)
    if math.isnan(f):
        return "\\textemdash{}"
    if math.isinf(f):
        return "\\ensuremath{\\infty}"
    return f"\\num{{{round(f):d}}}" if digits == 0 else f"\\num{{{f:.{digits}f}}}"


def est_ci(est: Any, lo: Any, hi: Any, digits: int = 2) -> str:
    """``1.23 (1.01–1.50)``; a dash when the estimate was suppressed or is missing."""
    if math.isnan(_float(est)):
        return "\\textemdash{}"
    return f"{num(est, digits)} ({num(lo, digits)}--{num(hi, digits)})"


def n_pct(n: Any, pct: Any, token: str) -> str:
    if _is_suppressed(n, token) or (isinstance(n, str) and n == SECONDARY_TOKEN):
        return num(n, token=token)
    return f"{num(n)} ({num(pct, 1)})"


def _tabular(spec: str, header: list[str], rows: Iterable[str]) -> str:
    body = "\n".join(rows)
    return (
        "\\setlength{\\tabcolsep}{4pt}\n"
        f"\\begin{{tabular}}{{{spec}}}\n\\toprule\n"
        + " & ".join(header)
        + " \\\\\n\\midrule\n"
        + body
        + "\n\\bottomrule\n\\end{tabular}"
    )


def _longtable(spec: str, header: list[str], rows: Iterable[str]) -> str:
    """A ``longtable`` whose caption (and label) is the macro's first argument."""
    head = " & ".join(header) + " \\\\"
    return (
        "\\setlength{\\tabcolsep}{4pt}\n"
        f"\\begin{{longtable}}{{{spec}}}\n\\caption{{#1}}\\\\\n\\toprule\n{head}\n\\midrule\n\\endfirsthead\n"
        f"\\toprule\n{head}\n\\midrule\n\\endhead\n\\bottomrule\n\\endfoot\n" + "\n".join(rows) + "\n\\end{longtable}"
    )


class TableSet:
    """Collect generated tables for one paper and write them as a macro file."""

    def __init__(self, prefix: str, token: str) -> None:
        self.prefix = prefix
        self.token = token
        self._denoms: dict[str, Any] = {}
        self.tables: dict[str, str] = {}
        self.arity: dict[str, int] = {}

    def add(self, name: str, tabular: str, *, n_args: int = 0) -> None:
        full = macro_name(self.prefix, "Table", name)
        if full in self.tables:
            msg = f"duplicate table {full}"
            raise ValueError(msg)
        self.tables[full] = tabular
        self.arity[full] = n_args

    def write(self, path: Path, header: str) -> Path:
        lines = [f"% {header}", "% GENERATED FILE — do not edit by hand (vamengoc release builder).", ""]
        for k, v in self.tables.items():
            args = f"[{self.arity[k]}]" if self.arity.get(k) else ""
            lines.append(f"\\newcommand{{\\{k}}}{args}{{%\n{v}%\n}}")
            lines.append("")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # ----------------------------------------------------------------------------- paper 1
    def characteristics(self, cat: pd.DataFrame, cont: pd.DataFrame, target: str, target_label: Lang) -> None:
        groups = [target, "Other vaccines", "All"]
        sex = cat[cat["variable"] == "sex"]
        denom: dict[str, Any] = {
            g: sex.loc[sex["group"] == g, "denominator"].iloc[0] if (sex["group"] == g).any() else None
            for g in groups[:2]
        }
        d_t, d_o = _float(denom[target]), _float(denom["Other vaccines"])
        denom["All"] = d_t + d_o if not (math.isnan(d_t) or math.isnan(d_o)) else None
        self._denoms = denom
        header = [
            hd("Characteristic", "Característica"),
            f"\\makecell{{{vl(*target_label)}\\\\(n\\,=\\,{num(denom[target])})}}",
            f"\\makecell{{{vl('Other vaccines', 'Otras vacunas')}\\\\(n\\,=\\,{num(denom['Other vaccines'])})}}",
            f"\\makecell{{{vl('All reports', 'Todas')}\\\\(n\\,=\\,{num(denom['All'])})}}",
        ]
        rows: list[str] = []

        def cont_row(var: str, label: Lang) -> None:
            cells = []
            for g in groups:
                r = cont[(cont["variable"] == var) & (cont["group"] == g)]
                if r.empty or math.isnan(_float(r["median"].iloc[0])):
                    cells.append("\\textemdash{}")
                else:
                    r0 = r.iloc[0]
                    cells.append(f"{num(r0['median'], 1)} ({num(r0['q1'], 1)}--{num(r0['q3'], 1)})")
            rows.append(f"{vl(*label)} & " + " & ".join(cells) + " \\\\")

        cont_row("age_months", ("Age, months, median (IQR)", "Edad, meses, mediana (RIC)"))
        for var, vlabel, levels in CHAR_VARIABLES:
            sub = cat[cat["variable"] == var]
            if sub.empty:
                continue
            present = list(dict.fromkeys(sub["level"].astype(str)))
            known = [code for code, _ in levels]
            ordered = [(c, lab) for c, lab in levels if c in present]
            ordered += [(c, MISSING if c == "Missing" else (c, c)) for c in present if c not in known and c != "No"]
            binary = len(levels) == 1
            if binary:
                code, _ = levels[0]
                rows.append(self._level_row(sub, code, vlabel, groups, indent=False))
                continue
            rows.append(f"\\multicolumn{{4}}{{@{{}}l}}{{{vl(*vlabel)}}} \\\\")
            for code, lab in ordered:
                rows.append(self._level_row(sub, code, lab, groups, indent=True))
        cont_row(
            "notification_delay_days",
            ("Notification delay, days, median (IQR)", "Demora de notificación, días, mediana (RIC)"),
        )
        self.add("Characteristics", _tabular("@{}" + FIRST.format("6.2cm") + "rrr@{}", header, rows))

    def _level_row(self, sub: pd.DataFrame, code: str, label: Lang, groups: list[str], *, indent: bool) -> str:
        """One level: the released groups, and "All" recomputed only when both are visible."""
        cells = []
        visible: list[float] = []
        for g in groups[:2]:
            r = sub[(sub["level"].astype(str) == code) & (sub["group"] == g)]
            if len(r):
                cells.append(n_pct(r["n"].iloc[0], r["pct"].iloc[0], self.token))
                visible.append(_float(r["n"].iloc[0]))
            else:
                cells.append(num(0))
                visible.append(0.0)
        if any(math.isnan(v) for v in visible):
            cells.append("[c]")
        else:
            total = sum(visible)
            den = _float(self._denoms.get("All"))
            cells.append(n_pct(total, 100 * total / den if den else math.nan, self.token))
        lead = "\\quad " if indent else ""
        return f"{lead}{vl(*label)} & " + " & ".join(cells) + " \\\\"

    def disproportionality(self, dp: pd.DataFrame, design: str, name: str, *, min_a: int | None) -> None:
        sub = dp[dp["design"] == design].copy()
        sub["_a"] = sub["a"].map(_float)
        if min_a is not None:
            sub = sub[sub["_a"] >= min_a]
        sub = sub.sort_values("_a", ascending=False, na_position="last")
        sig = "signal_primary" if "signal_primary" in sub.columns else "signal_any"
        header = [
            hd("Event", "Evento"),
            "$a$",
            "$E$",
            hd("ROR|(95% CI)", "ROR|(IC 95 %)"),
            "IC\\textsubscript{025}",
            "EB\\textsubscript{05}",
            hd("Methods", "Métodos"),
            hd("Signal", "Señal"),
        ]
        rows = []
        for _, r in sub.iterrows():
            flagged = str(r.get(sig)).lower() == "true"
            k = r.get("n_criteria_met")
            methods = (
                f"{int(_float(k))}/4"
                if not math.isnan(_float(k)) and not math.isnan(_float(r.get("ror")))
                else "\\textemdash{}"
            )
            rows.append(
                " & ".join(
                    [
                        vl(str(r["label_en"]), str(r["label_es"])),
                        num(r["a"], token=self.token),
                        num(r["expected"], 1),
                        est_ci(r["ror"], r["ror_lo"], r["ror_hi"]),
                        num(r["ic025"], 2),
                        num(r.get("eb05"), 2),
                        methods,
                        vl("Yes", "Sí") if flagged else "\\textemdash{}",
                    ]
                )
                + " \\\\"
            )
        self.add(name, _tabular("@{}" + FIRST.format("4.4cm") + "rrrrrcc@{}", header, rows))

    def designs(self, dp: pd.DataFrame, sizes: pd.DataFrame) -> None:
        sig = "signal_primary" if "signal_primary" in dp.columns else "signal_any"
        header = [
            hd("Comparator design", "Diseño de comparación"),
            hd("Target|reports", "Notificaciones|diana"),
            hd("Events|screened", "Eventos|evaluados"),
            hd("Signals|(primary)", "Señales|(principal)"),
            hd("Signals|(any method)", "Señales|(cualquier método)"),
        ]
        rows = []
        for d, lab in DESIGNS.items():
            g = dp[dp["design"] == d]
            if g.empty:
                continue
            sz = sizes[sizes["design"] == d]
            n_target = sz["n_target"].iloc[0] if len(sz) else None
            rows.append(
                f"{vl(*lab)} & {num(n_target, token=self.token)} & {num(len(g))} & "
                f"{num(int(g[sig].astype(str).str.lower().eq('true').sum()))} & "
                f"{num(int(g['signal_any'].astype(str).str.lower().eq('true').sum()))} \\\\"
            )
        self.add("Designs", _tabular("@{}" + FIRST.format("6.4cm") + "rrrr@{}", header, rows))

    def model_metrics(self, metrics: dict[str, dict[str, float]]) -> None:
        labels = {
            "logistic_test": ("Firth logistic regression (FLIC)", "Regresión logística de Firth (FLIC)"),
            "gbm_test": ("Gradient boosting (LightGBM)", "Potenciación del gradiente (LightGBM)"),
        }
        header = [
            hd("Model", "Modelo"),
            "AUROC",
            "AUPRC",
            "Brier",
            hd("Calibration|intercept", "Intercepto de|calibración"),
            hd("Calibration|slope", "Pendiente de|calibración"),
        ]
        rows = []
        for key, lab in labels.items():
            m = metrics.get(key)
            if not m:
                continue
            rows.append(
                f"{vl(*lab)} & {num(m.get('auroc'), 3)} & {num(m.get('auprc'), 3)} & {num(m.get('brier'), 4)} & "
                f"{num(m.get('cal_intercept'), 2)} & {num(m.get('cal_slope'), 2)} \\\\"
            )
        self.add("Models", _tabular("@{}" + FIRST.format("5.6cm") + "rrrrr@{}", header, rows))

    def rates(self, rates: pd.DataFrame) -> None:
        header = [
            hd("Year", "Año"),
            hd("Reports", "Notificaciones"),
            hd("Doses", "Dosis"),
            hd("Rate per 100 000 doses|(95% CI)", "Tasa por 100 000 dosis|(IC 95 %)"),
            hd("Ratio to|reference", "Razón respecto|a la referencia"),
        ]
        rows = [
            f"{int(_float(r['year']))} & {num(r['count'], token=self.token)} & {num(r['doses'])} & "
            f"{est_ci(r['rate_per_100k'], r['rate_lo'], r['rate_hi'], 1)} & {num(r['ratio_to_expected'], 2)} \\\\"
            for _, r in rates.iterrows()
        ]
        self.add("Rates", _tabular("@{}lrrrr@{}", header, rows))

    def lca_selection(self, sel: pd.DataFrame) -> None:
        header = [
            "$K$",
            hd("Log-likelihood", "Log-verosimilitud"),
            "BIC",
            "ICL-BIC",
            hd("Entropy", "Entropía") + " $R^2$",
            hd("Smallest|class, %", "Clase|menor, %"),
        ]
        rows = [
            f"{int(_float(r['k']))} & {num(r['loglik'], 1)} & {num(r['bic'], 1)} & {num(r['icl_bic'], 1)} & "
            f"{num(r['entropy_r2'], 3)} & {num(r['smallest_class_pct'], 1)} \\\\"
            for _, r in sel.iterrows()
        ]
        self.add("LCASelection", _tabular("@{}rrrrrr@{}", header, rows))

    def logistic(self, coef: pd.DataFrame, label: Callable[[str], Lang]) -> None:
        header = [
            hd("Term", "Término"),
            hd("Reports|with term", "Notificaciones|con el término"),
            hd("OR|(95% CI)", "OR|(IC 95 %)"),
            "$p$",
        ]
        rows = [
            f"{vl(*label(str(r['term'])))} & {num(r.get('n_with_term'), token=self.token)} & "
            f"{est_ci(r['or'], r['or_lo'], r['or_hi'])} & {format_p(r['p_value'])} \\\\"
            for _, r in coef.iterrows()
        ]
        self.add("Logistic", _tabular("@{}" + FIRST.format("6.4cm") + "rrr@{}", header, rows))

    # ----------------------------------------------------------------------------- paper 2
    def capability(self, cap: pd.DataFrame, cps: pd.DataFrame, attr: Callable[[str], Lang]) -> None:
        periods = [p for p in dict.fromkeys(cap["period"].astype(str)) if p != "all"]
        header = [
            hd("Attribute", "Atributo"),
            hd("Lots", "Lotes"),
            "\\makecell{$P_{pk}$ " + vl("(95% CI),", "(IC 95 %),") + "\\\\" + vl("all lots", "todos los lotes") + "}",
            *[f"\\makecell{{$P_{{pk}}$\\\\{p.replace('-', '--')}}}" for p in periods],
            hd("Change|point", "Punto de|cambio"),
        ]
        cp_year = {
            str(a): int(_float(y))
            for a, y in zip(cps.get("attribute", []), cps.get("production_year", []), strict=False)
        }
        rows = []
        for _, r in cap[cap["period"] == "all"].iterrows():
            a = str(r["attribute"])
            per = []
            for p in periods:
                rp = cap[(cap["attribute"] == a) & (cap["period"] == p)]
                per.append(num(rp["ppk"].iloc[0], 2) if len(rp) else "\\textemdash{}")
            rows.append(
                f"{vl(*attr(a))} & {num(r['n'])} & {est_ci(r['ppk'], r['ppk_lo'], r['ppk_hi'])} & "
                + " & ".join(per)
                + f" & {cp_year[a] if a in cp_year else chr(92) + 'textemdash{}'} \\\\"
            )
        spec = "@{}" + FIRST.format("4.2cm") + "r" + "r" * (1 + len(periods)) + "c@{}"
        self.add("Capability", _tabular(spec, header, rows))

    def gee(
        self,
        gee: pd.DataFrame,
        attr: Callable[[str], Lang],
        outcome: Callable[[str], Lang],
        name: str = "GEE",
        *,
        long: bool = False,
    ) -> None:
        single = gee[gee["model"] == "single"]
        crude = gee[gee["model"] == "crude"].set_index(["outcome", "exposure"]) if "model" in gee else gee
        has_crude = len(crude) > 0
        header = [
            hd("Outcome", "Desenlace"),
            hd("Lot attribute|(per SD)", "Atributo del lote|(por DE)"),
            *([hd("Crude OR|(95% CI)", "OR cruda|(IC 95 %)")] if has_crude else []),
            hd("Adjusted OR|(95% CI)", "OR ajustada|(IC 95 %)"),
            "$p$",
            "$q$ (FDR)",
        ]
        rows = []
        for oc, g in single.groupby("outcome", sort=False):
            first = True
            for _, r in g.iterrows():
                lab = attr(str(r["exposure"]))
                if str(r["negative_control"]).lower() == "true":
                    lab = (lab[0] + " (negative control)", lab[1] + " (control negativo)")
                crude_cell = ""
                if has_crude:
                    key = (r["outcome"], r["exposure"])
                    c = crude.loc[key] if key in crude.index else None
                    crude_cell = (
                        est_ci(c["or_per_sd"], c["or_lo"], c["or_hi"]) if c is not None else "\\textemdash{}"
                    ) + " & "
                rows.append(
                    f"{vl(*outcome(str(oc))) if first else ''} & {vl(*lab)} & {crude_cell}"
                    f"{est_ci(r['or_per_sd'], r['or_lo'], r['or_hi'])} & {format_p(r['p_value'])} & "
                    f"{format_p(r.get('p_bh'))} \\\\"
                )
                first = False
            rows.append("\\addlinespace")
        if rows and rows[-1] == "\\addlinespace":
            rows.pop()
        spec = "@{}" + FIRST.format("2.3cm") + FIRST.format("3.9cm") + ("r" if has_crude else "") + "rrr@{}"
        if long:
            self.add(name, _longtable(spec, header, rows), n_args=1)
        else:
            self.add(name, _tabular(spec, header, rows))

    def sensitivity(
        self,
        primary: pd.DataFrame,
        sens: pd.DataFrame,
        mixed: pd.DataFrame,
        lot: pd.DataFrame,
        attr: Callable[[str], Lang],
        outcome: Callable[[str], Lang],
    ) -> None:
        single = primary[
            (primary["model"] == "single") & ~primary["negative_control"].astype(str).str.lower().eq("true")
        ]
        cols = list(SENSITIVITY)
        header = [
            hd("Outcome / attribute", "Desenlace / atributo"),
            hd("Primary", "Principal"),
            *[hd(*SENSITIVITY[c]) for c in cols],
            hd("Random-|intercept", "Intercepto|aleatorio"),
            hd("Lot-level|model", "Modelo|por lote"),
        ]
        rows = []
        for _, r in single.iterrows():
            oc, ex = str(r["outcome"]), str(r["exposure"])
            cells = [est_ci(r["or_per_sd"], r["or_lo"], r["or_hi"])]
            for c in cols:
                s = sens[
                    (sens["sensitivity"] == c)
                    & (sens["outcome"] == oc)
                    & (sens["exposure"] == ex)
                    & (sens["model"] == "single")
                ]
                cells.append(
                    est_ci(s["or_per_sd"].iloc[0], s["or_lo"].iloc[0], s["or_hi"].iloc[0])
                    if len(s)
                    else "\\textemdash{}"
                )
            m = mixed[(mixed["outcome"] == oc) & (mixed["exposure"] == ex)]
            cells.append(
                est_ci(m["or_per_sd"].iloc[0], m["cri_lo"].iloc[0], m["cri_hi"].iloc[0]) if len(m) else "\\textemdash{}"
            )
            lv = lot[(lot["outcome"] == oc) & (lot["exposure"] == ex)]
            cells.append(
                est_ci(lv["or_per_sd"].iloc[0], lv["or_lo"].iloc[0], lv["or_hi"].iloc[0])
                if len(lv)
                else "\\textemdash{}"
            )
            o, a = outcome(oc), attr(ex)
            rows.append(f"{vl(o[0] + ' / ' + a[0], o[1] + ' / ' + a[1])} & " + " & ".join(cells) + " \\\\")
        self.add("Sensitivity", _tabular("@{}" + FIRST.format("5.2cm") + "r" * (len(cols) + 3) + "@{}", header, rows))

    def power(self, mde: pd.DataFrame, inc: pd.DataFrame, outcome: Callable[[str], Lang]) -> None:
        header = [
            hd("Outcome", "Desenlace"),
            hd("Prevalence,|%", "Prevalencia,|%"),
            "ICC",
            hd("Design|effect", "Efecto de|diseño"),
            hd("MDE,|OR per SD", "EMD,|OR por DE"),
            hd("AUC,|covariates", "AUC,|covariables"),
            "$\\Delta$AUC",
            "\\makecell{\\VLang{Permutation\\\\$p$}{$p$ de\\\\permutación}}",
        ]
        rows = []
        for _, r in mde.iterrows():
            oc = str(r["outcome"])
            i = inc[inc["outcome"] == oc] if len(inc) else inc
            ok = len(i) and str(i["estimable"].iloc[0]).lower() == "true"
            rows.append(
                f"{vl(*outcome(oc))} & {num(100 * _float(r['outcome_prevalence']), 1)} & {num(r['icc'], 3)} & "
                f"{num(r['design_effect'], 2)} & {num(r['mde_or_per_sd'], 2)} & "
                + (
                    f"{num(i['auc_base'].iloc[0], 3)} & {num(i['delta_auc'].iloc[0], 3)} & "
                    f"{format_p(i['perm_p'].iloc[0])}"
                    if ok
                    else "\\textemdash{} & \\textemdash{} & \\textemdash{}"
                )
                + " \\\\"
            )
        self.add("Power", _tabular("@{}" + FIRST.format("3.2cm") + "rrrrrrr@{}", header, rows))

    def equivalence(self, eq: pd.DataFrame, attr: Callable[[str], Lang]) -> None:
        header = [
            hd("Attribute", "Atributo"),
            hd("Difference|(90% CI)", "Diferencia|(IC 90 %)"),
            hd("Equivalent", "Equivalente"),
            hd("Hodges--Lehmann shift|(95% CI)", "Desplazamiento de|Hodges--Lehmann|(IC 95 %)"),
        ]
        rows = []
        for _, r in eq.iterrows():
            yes = str(r["equivalent"]).lower() == "true"
            rows.append(
                f"{vl(*attr(str(r['attribute'])))} & "
                f"{num(r['diff'], 3)} ({num(r['ci90_lo'], 3)} {TO} {num(r['ci90_hi'], 3)})"
                f" & {vl('Yes', 'Sí') if yes else vl('No', 'No')} & "
                f"{num(r['hl_shift'], 3)} ({num(r['hl_lo'], 3)} {TO} {num(r['hl_hi'], 3)}) \\\\"
            )
        self.add("Equivalence", _tabular("@{}" + FIRST.format("4.2cm") + "rcr@{}", header, rows))

    def linkage(self, by_year: pd.DataFrame) -> None:
        header = [
            hd("Year", "Año"),
            hd("Reports", "Notificaciones"),
            hd("Linked to|a lot", "Enlazadas|a un lote"),
            "\\%",
        ]
        rows = []
        for _, r in by_year.iterrows():
            n, k = _float(r["n_reports"]), _float(r["n_linked"])
            pct = 100 * k / n if n and not math.isnan(n) and not math.isnan(k) else math.nan
            rows.append(
                f"{int(_float(r['analytic_year']))} & {num(r['n_reports'], token=self.token)} & "
                f"{num(r['n_linked'], token=self.token)} & {num(pct, 1)} \\\\"
            )
        self.add("Linkage", _tabular("@{}lrrr@{}", header, rows))

    # ----------------------------------------------------------------------------- shared
    FIELDS: dict[str, Lang] = {  # noqa: RUF012 - read-only label map
        "sex": ("Sex", "Sexo"),
        "age_months": ("Age", "Edad"),
        "province": ("Province", "Provincia"),
        "vaccines": ("Vaccines", "Vacunas"),
        "doses": ("Doses", "Dosis"),
        "lots_exact": ("Lot number", "Número de lote"),
        "manufacturers": ("Manufacturer", "Fabricante"),
        "notification_date": ("Notification date", "Fecha de notificación"),
        "place": ("Place of vaccination", "Lugar de vacunación"),
    }

    def completeness(self, comp: pd.DataFrame) -> None:
        """Percentage of reports with each key field recorded, by file year."""
        years = sorted({int(_float(y)) for y in comp["file_year"]})
        header = [hd("Field", "Campo"), *[str(y) for y in years]]
        rows = []
        for field, lab in self.FIELDS.items():
            sub = comp[comp["field"] == field]
            if sub.empty:
                continue
            cells = []
            for y in years:
                r = sub[sub["file_year"].map(_float) == y]
                cells.append(num(r["pct_present"].iloc[0], 1) if len(r) else "\\textemdash{}")
            rows.append(f"{vl(*lab)} & " + " & ".join(cells) + " \\\\")
        self.add("Completeness", _tabular("@{}l" + "r" * len(years) + "@{}", header, rows))

    def plausibility(self, plaus: pd.DataFrame) -> None:
        """Data-quality checks over all years (Kahn et al. harmonised framework)."""
        header = [
            hd("Check", "Verificación"),
            hd("Category", "Categoría"),
            hd("Records", "Registros"),
            hd("Flagged", "Señalados"),
            "\\%",
        ]
        rows = []
        for _check, g in plaus.groupby("check", sort=False):
            n = pd.to_numeric(g["n_records"], errors="coerce").sum()
            k_raw = pd.to_numeric(g["n_flagged"], errors="coerce")
            suppressed = bool(g["n_flagged"].astype(str).eq(self.token).any())
            k = k_raw.sum()
            first = g.iloc[0]
            cat = str(first["category"]).split("/")[-1]
            cat_lab = {"temporal": ("Temporal", "Temporal"), "atemporal": ("Atemporal", "Atemporal")}.get(
                cat, (cat, cat)
            )
            flagged = (
                f"\\ensuremath{{\\geq}}{num(k)}"
                if suppressed and k > 0
                else num(self.token, token=self.token)
                if suppressed
                else num(k)
            )
            pct = "\\textemdash{}" if suppressed else num(100 * k / n if n else math.nan, 2)
            rows.append(
                f"{vl(str(first['label_en']), str(first['label_es']))} & {vl(*cat_lab)} & "
                f"{num(n)} & {flagged} & {pct} \\\\"
            )
        self.add("Plausibility", _tabular("@{}" + FIRST.format("7.4cm") + "lrrr@{}", header, rows))

    def cumulative_ic(self, cum: pd.DataFrame, events: list[str], labels: dict[str, Any]) -> None:
        """Year-by-year cumulative information component for selected events."""
        header = [
            hd("Event", "Evento"),
            hd("Through year", "Hasta el año"),
            "$a$",
            "$E$",
            hd("IC (95% CrI)", "IC (IC 95 % cred.)"),
        ]
        rows = []
        for e in events:
            g = cum[cum["event"] == e]
            if g.empty:
                continue
            lab = labels.get(e, {})
            first = True
            for _, r in g.iterrows():
                rows.append(
                    f"{vl(str(lab.get('label_en', e)), str(lab.get('label_es', e))) if first else ''} & "
                    f"{int(_float(r['year']))} & {num(r['a'], token=self.token)} & {num(r['expected'], 1)} & "
                    f"{est_ci(r['ic'], r['ic025'], r['ic975'])} \\\\"
                )
                first = False
            rows.append("\\addlinespace")
        if rows and rows[-1] == "\\addlinespace":
            rows.pop()
        self.add("CumulativeIC", _tabular("@{}" + FIRST.format("4.6cm") + "rrrr@{}", header, rows))

    def linkage_bias(self, bias: pd.DataFrame) -> None:
        """Characteristics of linked and unlinked reports (linkage bias)."""
        header = [
            hd("Reports", "Notificaciones"),
            "$n$",
            hd("Age, months,|median", "Edad, meses,|mediana"),
            hd("Female,|%", "Femenino,|%"),
            hd("Fever|\u226539 \u00b0C, %", "Fiebre|\u226539 \u00b0C, %"),
            hd("Hospitalised,|%", "Hospitalizado,|%"),
            hd("Co-administered,|%", "Coadministrada,|%"),
        ]
        rows = []
        for _, r in bias.iterrows():
            linked = str(r["linked"]).lower() == "true"
            lab = ("Linked to a lot", "Enlazadas a un lote") if linked else ("Not linked", "No enlazadas")
            rows.append(
                f"{vl(*lab)} & {num(r['n'], token=self.token)} & {num(r['age_months_median'], 1)} & "
                f"{num(r['female_pct'], 1)} & {num(r['fever39_pct'], 1)} & {num(r['hospitalized_pct'], 1)} & "
                f"{num(r['coadministered_pct'], 1)} \\\\"
            )
        self.add("LinkBias", _tabular("@{}lrrrrrr@{}", header, rows))

    def control_charts(self, summary: pd.DataFrame, attr: Callable[[str], Lang]) -> None:
        """Signals of the individuals and EWMA charts by attribute (Nelson rules)."""
        header = [
            hd("Attribute", "Atributo"),
            hd("Lots", "Lotes"),
            hd("Rule 1|(>3\u03c3)", "Regla 1|(>3\u03c3)"),
            hd("Rule 2|(9 on one|side)", "Regla 2|(9 de un|lado)"),
            hd("Rule 3|(6 in a|trend)", "Regla 3|(6 en|tendencia)"),
            hd("Rule 5|(2 of 3|>2\u03c3)", "Regla 5|(2 de 3|>2\u03c3)"),
            hd("EWMA|signals", "Señales|EWMA"),
        ]
        rows = [
            f"{vl(*attr(str(r['attribute'])))} & {num(r['n'])} & {num(r['rule1'])} & {num(r['rule2'])} & "
            f"{num(r['rule3'])} & {num(r['rule5'])} & {num(r['ewma_signals'])} \\\\"
            for _, r in summary.iterrows()
        ]
        self.add("ControlCharts", _tabular("@{}" + FIRST.format("4.2cm") + "rrrrrr@{}", header, rows))
