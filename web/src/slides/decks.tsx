// Slide decks for the periodic expert meetings. Every number and list on a slide is derived from
// the active bundle, so the decks update automatically when the release is rebuilt.

import type { ReactNode } from "react";
import { bandLine, controlChart, forest, heatmap } from "../charts/builders";
import type { EChartsOption } from "../charts/echarts";
import type { LegendItem } from "../components/ui";
import { bool, num, table, type Bundle } from "../data/bundle";
import { fmt, fmtCI, fmtPct } from "../data/format";
import { evaluateDesign, DEFAULT_THRESHOLDS } from "../data/signals";
import { completenessFloor, dqSummary, p1Summary, p2Summary, PRIMARY_DESIGN } from "../data/summary";
import { attributeLabel, eventLabel, outcomeLabel, termLabel, type LangApi } from "../i18n";
import { PIPELINE_STEPS } from "../content/pipeline";
import type { Tokens } from "../theme";

export interface Slide {
  kicker?: string;
  title: string;
  sub?: string;
  layout: "title" | "bullets" | "split" | "kpis" | "chart";
  bullets?: ReactNode[];
  kpis?: { v: string; l: string }[];
  chart?: { option: EChartsOption; label: string; legend?: LegendItem[] };
  notes: string;
}

export interface Deck {
  id: string;
  title: string;
  description: string;
  slides: Slide[];
}

interface Ctx {
  b: Bundle;
  L: LangApi;
  t: Tokens;
}

function list(items: string[], lang: string): string {
  if (!items.length) return lang === "es" ? "ninguna" : "none";
  return items.join(", ");
}

function rateChart({ b, L, t }: Ctx): EChartsOption {
  const rates = table(b, "p1_rates_target").filter((r) => Number.isFinite(num(r.rate_per_100k)));
  return bandLine(t, L.lang, {
    x: rates.map((r) => String(r.year)),
    y: rates.map((r) => num(r.rate_per_100k)),
    lo: rates.map((r) => num(r.rate_lo)),
    hi: rates.map((r) => num(r.rate_hi)),
    name: L.tr("Tasa por 100 000 dosis", "Rate per 100,000 doses"),
    bandLabel: L.tr("IC 95 %", "95% CI"),
    digits: 1,
    yMin: 0,
  });
}

function signalForest({ b, L, t }: Ctx): EChartsOption {
  const dp = table(b, "p1_disproportionality").filter((r) => r.design === PRIMARY_DESIGN);
  const ev = evaluateDesign(dp, PRIMARY_DESIGN, "ic", DEFAULT_THRESHOLDS);
  const rows = dp
    .filter((r) => Number.isFinite(num(r.ic)) && !ev.find((e) => e.event === r.event)?.withheld)
    .sort((a, c) => num(c.ic) - num(a.ic))
    .slice(0, 12);
  const sig = (r: (typeof rows)[number]) => !!ev.find((e) => e.event === r.event)?.signal;
  const pts = (want: boolean) =>
    rows
      .map((r, i) => ({ r, i }))
      .filter(({ r }) => sig(r) === want)
      .map(({ r, i }) => ({ cat: i, est: num(r.ic), lo: num(r.ic025), hi: num(r.ic975) }));
  return forest(t, L.lang, {
    categories: rows.map((r) => eventLabel(b, String(r.event), L.lang)),
    series: [
      { name: L.tr("Señal", "Signal"), color: t.s1, points: pts(true) },
      { name: L.tr("Sin señal", "No signal"), color: t.deemph, points: pts(false) },
    ],
    ref: 0,
    refLabel: "0",
    xName: "IC (IC025–IC975)",
  });
}

function completeness({ b, L, t }: Ctx): EChartsOption {
  const comp = table(b, "dq_completeness");
  const years = [...new Set(comp.map((r) => num(r.file_year)))].sort((a, c) => a - c);
  const fields = [...new Set(comp.map((r) => String(r.field)))];
  return heatmap(t, L.lang, {
    x: years.map(String),
    y: fields.map((f) => f.replace(/_/g, " ")),
    cells: comp.map((r) => [years.indexOf(num(r.file_year)), fields.indexOf(String(r.field)), num(r.pct_present)]),
    min: completenessFloor(comp.map((r) => num(r.pct_present))),
    max: 100,
    digits: 1,
    valueLabel: L.tr("Completitud (%)", "Completeness (%)"),
    showLabels: true,
  });
}

function capabilityForest({ b, L, t }: Ctx): EChartsOption {
  const est = table(b, "p2_capability").filter((r) => bool(r.estimable) && r.period === "all");
  return forest(t, L.lang, {
    categories: est.map((r) => attributeLabel(b, String(r.attribute), L.lang)),
    series: [
      {
        name: "Ppk",
        color: t.s1,
        points: est.map((r, i) => ({ cat: i, est: num(r.ppk), lo: num(r.ppk_lo), hi: num(r.ppk_hi) })),
      },
    ],
    ref: 1,
    refLabel: fmt(1, L.lang, 2),
    extraRefs: [{ value: 1.33, label: fmt(1.33, L.lang, 2) }],
    xName: L.tr("Ppk (IC 95 %), todos los lotes", "Ppk (95% CI), all lots"),
  });
}

function associationForest({ b, L, t }: Ctx, outcome: string): EChartsOption {
  const rows = table(b, "p2_gee_primary").filter((r) => r.outcome === outcome && r.model === "single");
  return forest(t, L.lang, {
    categories: rows.map(
      (r) =>
        `${attributeLabel(b, String(r.exposure), L.lang)}${bool(r.negative_control) ? L.tr(" (control negativo)", " (negative control)") : ""}`,
    ),
    series: [
      {
        name: L.tr("OR ajustada por DE", "Adjusted OR per SD"),
        color: t.s1,
        points: rows.map((r, i) => ({ cat: i, est: num(r.or_per_sd), lo: num(r.or_lo), hi: num(r.or_hi) })),
      },
    ],
    log: true,
    ref: 1,
    refLabel: "1",
    xName: L.tr("OR por DE (IC 95 %)", "OR per SD (95% CI)"),
  });
}

function controlFor({ b, L, t }: Ctx, attribute: string): EChartsOption {
  const ser = table(b, "p2_lot_series").filter((r) => r.attribute === attribute);
  return controlChart(t, L.lang, {
    seq: ser.map((r) => num(r.seq)),
    values: ser.map((r) => num(r.z)),
    flagged: ser.map((r) => bool(r.rule1)),
    years: ser.map((r) => num(r.production_year)),
    name: "z",
    flaggedName: L.tr("Fuera de control", "Out of control"),
    yName: "z",
    limits: [
      { value: 3, label: "+3σ" },
      { value: -3, label: "−3σ" },
    ],
    lotLabel: L.tr("Lote", "Lot"),
    yearLabel: L.tr("año", "year"),
    zoomStartPct: 0,
  });
}

function hospForest({ b, L, t }: Ctx): EChartsOption {
  const rows = table(b, "p1_seriousness_logistic")
    .filter((r) => num(r.or) > 0 && Number.isFinite(num(r.or_lo)))
    .sort((a, c) => num(c.or) - num(a.or))
    .slice(0, 12);
  return forest(t, L.lang, {
    categories: rows.map((r) => termLabel(b, String(r.term), L.lang)),
    series: [
      {
        name: "OR",
        color: t.s1,
        points: rows.map((r, i) => ({ cat: i, est: num(r.or), lo: num(r.or_lo), hi: num(r.or_hi) })),
      },
    ],
    log: true,
    ref: 1,
    refLabel: "1",
    xName: L.tr("OR de hospitalización (IC 95 %)", "OR of hospitalisation (95% CI)"),
  });
}

export function buildDecks(b: Bundle, L: LangApi, t: Tokens): Deck[] {
  const ctx: Ctx = { b, L, t };
  const { tr, lang } = L;
  const p1 = p1Summary(b);
  const p2 = p2Summary(b);
  const dq = dqSummary(b);
  const ev = (e: string) => eventLabel(b, e, lang);
  const synth = b.meta.synthetic
    ? tr(" — DATOS SINTÉTICOS, no son resultados reales", " — SYNTHETIC DATA, not real results")
    : "";
  const date = b.meta.generated_utc.slice(0, 10);
  const authors = "R. A. Matos Arderí · A. Ponce González";
  const sig = [...p2.significant].sort((a, c) => num(a.p_bh) - num(c.p_bh));
  const topAssoc = sig[0];
  const topAttr = topAssoc ? String(topAssoc.exposure) : "endotoxin";
  const firstOutcome = String(table(b, "p2_gee_primary")[0]?.outcome ?? "ev_fever_39");
  const trend = p1.trend;

  const followUp: Deck = {
    id: "seguimiento",
    title: tr("Reunión periódica de seguimiento", "Periodic follow-up meeting"),
    description: tr(
      "Estado del pipeline, calidad de datos y decisiones que el grupo de expertos debe tomar.",
      "Pipeline status, data quality and the decisions the expert group needs to take.",
    ),
    slides: [
      {
        layout: "title",
        kicker: tr("Instituto Finlay de Vacunas · DICEI", "Finlay Vaccine Institute · DICEI"),
        title: tr("VA-MENGOC-BC: seguimiento del proyecto de evidencia", "VA-MENGOC-BC: evidence project follow-up"),
        sub: `${authors} · ${date}${synth}`,
        notes: tr(
          "Presentar el objetivo: dos artículos a partir de la farmacovigilancia y de la liberación de lotes. Recordar que todo lo mostrado procede del release con control de divulgación.",
          "Introduce the goal: two papers from pharmacovigilance and lot release data. Remind the audience that everything shown comes from the disclosure-controlled release.",
        ),
      },
      {
        layout: "bullets",
        kicker: tr("Agenda", "Agenda"),
        title: tr("Qué revisaremos hoy", "What we will review today"),
        bullets: [
          tr("Estado del pipeline y de los datos", "Status of the pipeline and the data"),
          tr("Calidad de los datos por año", "Data quality by year"),
          tr("Resultados principales de los dos estudios", "Main results of the two studies"),
          tr("Decisiones que necesitamos del grupo", "Decisions we need from the group"),
          tr("Próximos pasos y calendario de envío", "Next steps and submission timeline"),
        ],
        notes: tr("Duración prevista: 45 minutos, 15 de discusión.", "Planned length: 45 minutes, 15 for discussion."),
      },
      {
        layout: "kpis",
        kicker: tr("Estado", "Status"),
        title: tr("Los datos en cifras", "The data in figures"),
        kpis: [
          { v: fmt(dq.nRecords, lang), l: tr("registros de ESAVI evaluados", "AEFI records assessed") },
          { v: fmt(p1.targetReports, lang), l: tr("notificaciones con VA-MENGOC-BC", "reports with VA-MENGOC-BC") },
          { v: fmt(p2.nLots, lang), l: tr("lotes liberados", "released lots") },
          { v: fmt(dq.nChecks, lang), l: tr("comprobaciones de calidad", "quality checks") },
        ],
        notes: tr("Las cifras se recalculan en cada ejecución del pipeline.", "Figures are recomputed at every pipeline run."),
      },
      {
        layout: "split",
        kicker: tr("Método", "Method"),
        title: tr("Ocho pasos automáticos y auditables", "Eight automated, auditable steps"),
        bullets: PIPELINE_STEPS.map((s) => `${lang === "es" ? s.title[0] : s.title[1]}: ${lang === "es" ? s.guarantee[0] : s.guarantee[1]}`),
        notes: tr(
          "Insistir en la seudonimización en la ingesta y en el control de divulgación antes de publicar.",
          "Stress pseudonymisation at ingestion and disclosure control before release.",
        ),
      },
      {
        layout: "chart",
        kicker: tr("Calidad de datos", "Data quality"),
        title: tr("Completitud por campo y año", "Completeness by field and year"),
        chart: { option: completeness(ctx), label: tr("Completitud", "Completeness") },
        notes: tr(
          "Identificar los campos con menor completitud y si responden a cambios del formulario.",
          "Identify the least complete fields and whether they reflect changes in the form.",
        ),
      },
      {
        layout: "bullets",
        kicker: tr("Decisiones", "Decisions"),
        title: tr("Lo que necesitamos del grupo", "What we need from the group"),
        bullets: [
          tr("Confirmar el significado de las siglas de vacunas y códigos de provincia", "Confirm vaccine acronyms and province codes"),
          tr("Fecha que define el año analítico (vacunación o notificación)", "Date defining the analytic year (vaccination or notification)"),
          tr("Clasificación de gravedad y codificación MedDRA/CIE-10", "Seriousness classification and MedDRA/ICD-10 coding"),
          tr("Qué atributos de calidad pueden publicarse en unidades absolutas", "Which quality attributes may be published in absolute units"),
          tr("Dosis administradas en 2025 y tasa de referencia del programa", "Doses administered in 2025 and the programme reference rate"),
        ],
        notes: tr(
          "Fuente: docs/OPEN_QUESTIONS.md. Registrar cada decisión en el acta y en el registro de decisiones.",
          "Source: docs/OPEN_QUESTIONS.md. Record every decision in the minutes and the decision log.",
        ),
      },
      {
        layout: "bullets",
        kicker: tr("Próximos pasos", "Next steps"),
        title: tr("Hacia el envío de los artículos", "Towards submission"),
        bullets: [
          tr("Ejecutar el pipeline sobre los datos reales (fase 1, en local)", "Run the pipeline on the real data (phase 1, local)"),
          tr("Revisión caso a caso de las señales no descritas por el comité", "Case-by-case review of undescribed signals by the committee"),
          tr("Aprobación ética, financiación y contribuciones CRediT", "Ethics approval, funding and CRediT contributions"),
          tr("Envío: artículo 1 a Drug Safety, artículo 2 a Vaccine (sin APC)", "Submission: paper 1 to Drug Safety, paper 2 to Vaccine (no APC)"),
        ],
        notes: tr("Acordar responsables y fechas antes de cerrar.", "Agree owners and dates before closing."),
      },
    ],
  };

  const pvDeck: Deck = {
    id: "p1",
    title: tr("Artículo 1: seguridad poscomercialización", "Paper 1: post-marketing safety"),
    description: tr(
      "Tasas, señales de desproporcionalidad, fenotipos latentes y hospitalización.",
      "Rates, disproportionality signals, latent phenotypes and hospitalisation.",
    ),
    slides: [
      {
        layout: "title",
        kicker: tr("Artículo 1 · Drug Safety", "Paper 1 · Drug Safety"),
        title: tr(
          `Seguridad poscomercialización de VA-MENGOC-BC en Cuba, ${p1.firstYear}–${p1.lastYear}`,
          `Post-marketing safety of VA-MENGOC-BC in Cuba, ${p1.firstYear}–${p1.lastYear}`,
        ),
        sub: `${authors} · ${date}${synth}`,
        notes: tr("Estudio de desproporcionalidad según READUS-PV.", "Disproportionality study reported per READUS-PV."),
      },
      {
        layout: "bullets",
        kicker: tr("Diseño", "Design"),
        title: tr("Pregunta y diseño", "Question and design"),
        bullets: [
          tr("Notificaciones espontáneas de ESAVI del sistema nacional", "Spontaneous AEFI reports from the national system"),
          tr(`${p1.designs.length} diseños comparadores, incluido un comparador activo en lactantes`, `${p1.designs.length} comparator designs, including an infant active comparator`),
          tr("ROR, PRR, IC (BCPNN) y EBGM; criterio preespecificado IC025 > 0 con a ≥ 3", "ROR, PRR, IC (BCPNN) and EBGM; prespecified criterion IC025 > 0 with a ≥ 3"),
          tr("Clases latentes de coocurrencia y modelo de hospitalización con validación temporal", "Latent co-occurrence classes and a temporally validated hospitalisation model"),
        ],
        notes: tr("La desproporcionalidad genera hipótesis; no estima riesgos.", "Disproportionality generates hypotheses; it does not estimate risks."),
      },
      {
        layout: "kpis",
        kicker: tr("Resultados", "Results"),
        title: tr("Cifras principales", "Headline figures"),
        kpis: [
          { v: fmt(p1.targetReports, lang), l: tr("notificaciones con la vacuna", "reports with the vaccine") },
          {
            v: fmt(trend.pooled_rate_per_100k, lang, 1),
            l: tr("notificaciones por 100 000 dosis", "reports per 100,000 doses"),
          },
          {
            v: fmt(trend.rr_per_year, lang, 3),
            l: tr(
              `razón de tasas anual (${fmt(trend.rr_lo, lang, 2)}–${fmt(trend.rr_hi, lang, 2)})`,
              `annual rate ratio (${fmt(trend.rr_lo, lang, 2)}–${fmt(trend.rr_hi, lang, 2)})`,
            ),
          },
          { v: fmt(p1.flagged.length, lang), l: tr(`señales; ${p1.robust.length} robustas`, `signals; ${p1.robust.length} robust`) },
        ],
        notes: tr("Robusta: señal en todos los diseños comparadores.", "Robust: signal in every comparator design."),
      },
      {
        layout: "chart",
        kicker: tr("Tasas", "Rates"),
        title: tr("Tasa de notificación por año", "Reporting rate by year"),
        chart: {
          option: rateChart(ctx),
          label: tr("Tasa por año", "Rate by year"),
          legend: [
            { label: tr("Tasa", "Rate"), color: t.s1 },
            { label: tr("IC 95 %", "95% CI"), color: t.band2, shape: "band" },
          ],
        },
        notes: tr("Comparar con la tasa de referencia del programa.", "Compare with the programme reference rate."),
      },
      {
        layout: "chart",
        kicker: tr("Señales", "Signals"),
        title: tr("Desproporcionalidad en el diseño principal", "Disproportionality in the primary design"),
        chart: {
          option: signalForest(ctx),
          label: tr("Gráfico de bosque del IC", "IC forest plot"),
          legend: [
            { label: tr("Señal (IC025 > 0, a ≥ 3)", "Signal (IC025 > 0, a ≥ 3)"), color: t.s1, shape: "dot" },
            { label: tr("Sin señal", "No signal"), color: t.deemph, shape: "dot" },
          ],
        },
        notes: tr("Doce eventos con mayor IC; en azul, señales con el criterio preespecificado.", "Twelve events with the highest IC; signals under the prespecified criterion in blue."),
      },
      {
        layout: "split",
        kicker: tr("Interpretación", "Interpretation"),
        title: tr("Reacciones esperadas y no descritas", "Expected and undescribed reactions"),
        bullets: [
          tr(`Esperadas: ${list(p1.expected.map(ev), lang)}`, `Expected: ${list(p1.expected.map(ev), lang)}`),
          tr(`No descritas en la ficha técnica: ${list(p1.emerging.map(ev), lang)}`, `Not in the product information: ${list(p1.emerging.map(ev), lang)}`),
          tr(`Robustas en todos los diseños: ${list(p1.robust.map(ev), lang)}`, `Robust across designs: ${list(p1.robust.map(ev), lang)}`),
        ],
        notes: tr("Las no descritas requieren revisión clínica caso a caso.", "Undescribed signals require case-by-case clinical review."),
      },
      {
        layout: "chart",
        kicker: tr("Hospitalización", "Hospitalisation"),
        title: tr(
          `Factores asociados (AUROC temporal ${fmt(p1.auroc, lang, 2)})`,
          `Associated factors (temporal AUROC ${fmt(p1.auroc, lang, 2)})`,
        ),
        chart: { option: hospForest(ctx), label: tr("Odds ratios de hospitalización", "Hospitalisation odds ratios") },
        notes: tr("Regresión logística de Firth; doce términos con mayor OR.", "Firth logistic regression; twelve terms with the largest OR."),
      },
      {
        layout: "bullets",
        kicker: tr("Para el comité", "For the committee"),
        title: tr("Limitaciones y preguntas", "Limitations and questions"),
        bullets: [
          tr("Infranotificación y notificación estimulada no medibles", "Under-reporting and stimulated reporting cannot be measured"),
          tr("Eventos no validados frente a las definiciones de Brighton", "Events not validated against Brighton definitions"),
          tr("Sin dosis por edad, número de dosis ni provincia", "No doses by age, dose number or province"),
          tr("¿Revisará el comité nacional los casos de las señales no descritas?", "Will the national committee review the cases behind undescribed signals?"),
        ],
        notes: tr("Recoger compromisos en el registro de decisiones.", "Capture commitments in the decision log."),
      },
    ],
  };

  const lotDeck: Deck = {
    id: "p2",
    title: tr("Artículo 2: calidad de lotes y reactogenicidad", "Paper 2: lot quality and reactogenicity"),
    description: tr(
      "Capacidad de proceso, gráficos de control y asociación con las notificaciones.",
      "Process capability, control charts and association with the reports.",
    ),
    slides: [
      {
        layout: "title",
        kicker: tr("Artículo 2 · Vaccine", "Paper 2 · Vaccine"),
        title: tr(
          "Atributos de liberación de los lotes y reactogenicidad de VA-MENGOC-BC",
          "Lot release attributes and reactogenicity of VA-MENGOC-BC",
        ),
        sub: `${authors} · ${date}${synth}`,
        notes: tr("Estudio observacional que enlaza dos registros (RECORD-PE).", "Observational study linking two registers (RECORD-PE)."),
      },
      {
        layout: "bullets",
        kicker: tr("Diseño", "Design"),
        title: tr("Pregunta y diseño", "Question and design"),
        bullets: [
          tr("¿Explica la variación dentro de especificación el perfil de las notificaciones?", "Does within-specification variation explain the profile of the reports?"),
          tr("Enlace notificación–lote exacto, de núcleo y aproximado", "Exact, core and fuzzy report–lot linkage"),
          tr("Diseño de solo casos: GEE con correlación dentro del lote", "Case-only design: GEE with within-lot correlation"),
          tr("Control negativo, análisis de sensibilidad y efecto mínimo detectable", "Negative control, sensitivity analyses and minimum detectable effect"),
        ],
        notes: tr("Los valores de los lotes se publican solo normalizados.", "Lot values are released only in normalised form."),
      },
      {
        layout: "kpis",
        kicker: tr("Datos", "Data"),
        title: tr("Enlace y muestra analizada", "Linkage and analysed sample"),
        kpis: [
          { v: fmt(p2.nLots, lang), l: tr("lotes liberados", "released lots") },
          { v: fmtPct(p2.linkRate * 100, lang), l: tr("notificaciones enlazadas", "reports linked") },
          { v: fmt(p2.nAnalysed, lang), l: tr(`notificaciones en ${fmt(p2.nLotsAnalysed, lang)} lotes`, `reports in ${fmt(p2.nLotsAnalysed, lang)} lots`) },
          { v: `${p2.significant.length}/${p2.nAssociations}`, l: tr("asociaciones con q < 0,05", "associations with q < 0.05") },
        ],
        notes: tr("Revisar el sesgo de enlace antes de interpretar.", "Check linkage bias before interpreting."),
      },
      {
        layout: "chart",
        kicker: tr("Proceso", "Process"),
        title: tr("Capacidad de proceso por atributo", "Process capability by attribute"),
        chart: { option: capabilityForest(ctx), label: "Ppk" },
        notes: tr(
          `Atributos con Ppk < 1: ${list(p2.capabilityBelow1.map((a) => attributeLabel(b, a, lang)), lang)}.`,
          `Attributes with Ppk < 1: ${list(p2.capabilityBelow1.map((a) => attributeLabel(b, a, lang)), lang)}.`,
        ),
      },
      {
        layout: "chart",
        kicker: tr("Proceso", "Process"),
        title: tr(`Gráfico de control: ${attributeLabel(b, topAttr, lang)}`, `Control chart: ${attributeLabel(b, topAttr, lang)}`),
        chart: {
          option: controlFor(ctx, topAttr),
          label: tr("Gráfico de control", "Control chart"),
          legend: [
            { label: "z", color: t.s1 },
            { label: tr("Fuera de control", "Out of control"), color: t.critical, shape: "dot" },
            { label: tr("Límites ±3σ", "±3σ limits"), color: t.muted, shape: "dashed" },
          ],
        },
        notes: tr("Valores estandarizados por lote en orden de producción.", "Standardised values per lot in production order."),
      },
      {
        layout: "chart",
        kicker: tr("Asociación", "Association"),
        title: tr(
          `Atributos de los lotes y ${outcomeLabel(b, firstOutcome, lang).toLowerCase()}`,
          `Lot attributes and ${outcomeLabel(b, firstOutcome, lang).toLowerCase()}`,
        ),
        chart: { option: associationForest(ctx, firstOutcome), label: tr("Asociaciones", "Associations") },
        notes: topAssoc
          ? tr(
              `Asociación más fuerte tras FDR: ${attributeLabel(b, String(topAssoc.exposure), lang)} y ${outcomeLabel(b, String(topAssoc.outcome), lang)}, OR ${fmtCI(topAssoc.or_per_sd, topAssoc.or_lo, topAssoc.or_hi, lang)}.`,
              `Strongest association after FDR: ${attributeLabel(b, String(topAssoc.exposure), lang)} and ${outcomeLabel(b, String(topAssoc.outcome), lang)}, OR ${fmtCI(topAssoc.or_per_sd, topAssoc.or_lo, topAssoc.or_hi, lang)}.`,
            )
          : tr("Ninguna asociación supera la corrección FDR.", "No association survives FDR correction."),
      },
      {
        layout: "bullets",
        kicker: tr("Para el comité", "For the committee"),
        title: tr("Limitaciones y decisiones", "Limitations and decisions"),
        bullets: [
          tr("No se registran dosis distribuidas por lote: no hay incidencia por lote", "Doses distributed per lot are not recorded: no per-lot incidence"),
          tr("Los ensayos describen el lote al liberarse, no tras el almacenamiento", "Release tests describe the lot at release, not after storage"),
          tr("¿Qué atributos pueden publicarse en unidades absolutas?", "Which attributes may be published in absolute units?"),
          tr("¿Se dispone de datos de estabilidad para un análisis complementario?", "Are stability data available for a complementary analysis?"),
        ],
        notes: tr("Las respuestas se reflejan en configs/ y en el acta.", "Answers are reflected in configs/ and in the minutes."),
      },
    ],
  };

  return [followUp, pvDeck, lotDeck];
}
