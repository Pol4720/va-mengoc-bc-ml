// Paper 1: reporting rates, disproportionality with client-side re-thresholding, event profile,
// latent phenotypes and the hospitalisation model.

import { useMemo, useState } from "react";
import { bandLine, bars, barsHeight, forest, forestHeight, heatmap, lines } from "../charts/builders";
import { Chart } from "../components/Chart";
import { Badge, Figure, Legend, SectionTitle, StatTile, type TableData } from "../components/ui";
import { isSuppressed, num, object, table, type Row } from "../data/bundle";
import { fmt, fmtCI, fmtP, fmtPct } from "../data/format";
import { DEFAULT_THRESHOLDS, evaluateDesign, type Criterion, type SignalRow } from "../data/signals";
import { p1Summary, PRIMARY_DESIGN, type Changepoints, type SeriousnessMetrics } from "../data/summary";
import { DESIGN_LABELS, eventLabel, pick, termLabel, useLang } from "../i18n";
import { useBundle } from "../state";
import { useTokens } from "../theme";

const CRITERIA: { value: Criterion; label: string; es: string; en: string }[] = [
  { value: "ic", label: "IC", es: "IC025 > 0 (BCPNN)", en: "IC025 > 0 (BCPNN)" },
  { value: "ror", label: "ROR", es: "Límite inferior del ROR > 1", en: "ROR lower bound > 1" },
  { value: "prr", label: "PRR", es: "PRR ≥ 2 y χ² ≥ 4", en: "PRR ≥ 2 and χ² ≥ 4" },
  { value: "ebgm", label: "EBGM", es: "EB05 ≥ 2 (MGPS)", en: "EB05 ≥ 2 (MGPS)" },
  { value: "consensus2", label: "≥2", es: "Al menos dos métodos", en: "At least two methods" },
];

function measureOf(r: Row, criterion: Criterion): { est: number; lo: number; hi: number; log: boolean } {
  switch (criterion) {
    case "ic":
      return { est: num(r.ic), lo: num(r.ic025), hi: num(r.ic975), log: false };
    case "ebgm":
      return { est: num(r.ebgm), lo: num(r.eb05), hi: num(r.eb95), log: true };
    case "prr":
      return { est: num(r.prr), lo: num(r.prr_lo), hi: num(r.prr_hi), log: true };
    default:
      return { est: num(r.ror), lo: num(r.ror_lo), hi: num(r.ror_hi), log: true };
  }
}

export function Pharmacovigilance() {
  const { bundle } = useBundle();
  const { lang, tr } = useLang();
  const t = useTokens();
  const s = useMemo(() => p1Summary(bundle), [bundle]);
  const [design, setDesign] = useState(PRIMARY_DESIGN);
  const [criterion, setCriterion] = useState<Criterion>("ic");
  const [minReports, setMinReports] = useState(DEFAULT_THRESHOLDS.minReports);
  const [onlySignals, setOnlySignals] = useState(false);

  const dp = table(bundle, "p1_disproportionality");
  const designs = useMemo(() => [...new Set(dp.map((r) => String(r.design)))], [dp]);
  const thresholds = useMemo(() => ({ ...DEFAULT_THRESHOLDS, minReports }), [minReports]);
  const evaluated: SignalRow[] = useMemo(
    () => evaluateDesign(dp, design, criterion, thresholds),
    [dp, design, criterion, thresholds],
  );
  const designRows = useMemo(() => dp.filter((r) => r.design === design), [dp, design]);
  const nSignals = evaluated.filter((r) => r.signal).length;
  const nPipeline = evaluated.filter((r) => r.pipelineSignal).length;
  const agree = evaluated.filter((r) => !r.withheld && r.signal === r.pipelineSignal).length;
  const comparable = evaluated.filter((r) => !r.withheld).length;
  const sizes = table(bundle, "p1_design_sizes").find((r) => r.design === design);
  const label = (ev: string) => eventLabel(bundle, ev, lang);

  // ---- Rates ----------------------------------------------------------------------------------
  const rates = useMemo(
    () => table(bundle, "p1_rates_target").filter((r) => Number.isFinite(num(r.rate_per_100k))),
    [bundle],
  );
  const expectedRate = useMemo(() => {
    const r = rates.find((x) => num(x.ratio_to_expected) > 0);
    return r ? num(r.rate_per_100k) / num(r.ratio_to_expected) : NaN;
  }, [rates]);
  const rateOption = useMemo(
    () =>
      bandLine(t, lang, {
        x: rates.map((r) => String(r.year)),
        y: rates.map((r) => num(r.rate_per_100k)),
        lo: rates.map((r) => num(r.rate_lo)),
        hi: rates.map((r) => num(r.rate_hi)),
        name: tr("Tasa por 100 000 dosis", "Rate per 100,000 doses"),
        bandLabel: tr("IC 95 %", "95% CI"),
        digits: 1,
        yMin: 0,
        refs: Number.isFinite(expectedRate)
          ? [{ value: expectedRate, label: tr(`Referencia del programa (${fmt(expectedRate, lang)})`, `Programme reference (${fmt(expectedRate, lang)})`) }]
          : undefined,
      }),
    [t, lang, rates, expectedRate, tr],
  );

  // ---- Monthly series with change points ------------------------------------------------------
  const monthly = table(bundle, "p1_monthly_target");
  const cps = object<{ target?: Changepoints }>(bundle, "p1_monthly_changepoints")?.target;
  const segMean = useMemo(
    () =>
      monthly.map((r) => {
        const m = String(r.month);
        const seg = cps?.segments.find((g) => g.start <= m && m <= g.end);
        return seg ? seg.mean_count : null;
      }),
    [monthly, cps],
  );
  const monthlyOption = useMemo(
    () =>
      lines(t, lang, {
        x: monthly.map((r) => String(r.month)),
        series: [
          { name: tr("Notificaciones mensuales", "Monthly reports"), color: t.s1, values: monthly.map((r) => num(r.count)) },
          { name: tr("Media del segmento (PELT)", "Segment mean (PELT)"), color: t.s2, values: segMean, step: true },
        ],
        zoom: true,
        yMin: 0,
      }),
    [t, lang, monthly, segMean, tr],
  );

  // ---- Forest of the selected measure ---------------------------------------------------------
  const forestData = useMemo(() => {
    const rows = designRows
      .map((r) => ({ r, m: measureOf(r, criterion), e: evaluated.find((x) => x.event === r.event) }))
      .filter((x) => Number.isFinite(x.m.est) && x.e && !x.e.withheld && (!onlySignals || x.e.signal))
      .sort((a, b) => b.m.est - a.m.est);
    const categories = rows.map((x) => label(String(x.r.event)));
    const mk = (sig: boolean) =>
      rows
        .map((x, i) => ({ x, i }))
        .filter(({ x }) => !!x.e?.signal === sig)
        .map(({ x, i }) => ({
          cat: i,
          est: x.m.est,
          lo: x.m.lo,
          hi: x.m.hi,
          tip: [
            `a = ${fmt(x.r.a, lang)}`,
            tr(`métodos: ${x.e?.methods ?? 0}/4`, `methods: ${x.e?.methods ?? 0}/4`),
            x.e?.pipelineSignal ? tr("señal preespecificada", "prespecified signal") : "",
          ].filter(Boolean),
        }));
    const log = measureOf(designRows[0] ?? {}, criterion).log;
    return { categories, signal: mk(true), other: mk(false), log };
  }, [designRows, criterion, evaluated, onlySignals, lang, tr]); // eslint-disable-line react-hooks/exhaustive-deps

  const measureName =
    criterion === "ic"
      ? tr("IC (IC025–IC975)", "IC (IC025–IC975)")
      : criterion === "ebgm"
        ? tr("EBGM (EB05–EB95)", "EBGM (EB05–EB95)")
        : criterion === "prr"
          ? tr("PRR (IC 95 %)", "PRR (95% CI)")
          : tr("ROR (IC 95 %)", "ROR (95% CI)");
  const forestOption = useMemo(
    () =>
      forest(t, lang, {
        categories: forestData.categories,
        series: [
          { name: tr("Señal con la regla elegida", "Signal under the chosen rule"), color: t.s1, points: forestData.signal },
          { name: tr("Sin señal", "No signal"), color: t.deemph, points: forestData.other },
        ],
        log: forestData.log,
        ref: forestData.log ? 1 : 0,
        refLabel: forestData.log ? "1" : "0",
        extraRefs:
          criterion === "ebgm"
            ? [{ value: DEFAULT_THRESHOLDS.eb05, label: tr("umbral EB05", "EB05 threshold") }]
            : criterion === "prr"
              ? [{ value: DEFAULT_THRESHOLDS.prr, label: tr("umbral PRR", "PRR threshold") }]
              : undefined,
        xName: measureName,
      }),
    [t, lang, forestData, criterion, measureName, tr],
  );

  const dpTable: TableData = useMemo(() => {
    const rows = designRows
      .map((r) => ({ r, e: evaluated.find((x) => x.event === r.event) }))
      .filter((x) => !onlySignals || x.e?.signal);
    const exp = (ev: string) => !!bundle.labels.events[ev]?.expected;
    return {
      columns: [
        { key: "event", label: tr("Evento", "Event") },
        { key: "a", label: "a", numeric: true },
        { key: "expected", label: tr("Esperado", "Expected"), numeric: true },
        { key: "ror", label: tr("ROR (IC 95 %)", "ROR (95% CI)"), numeric: true },
        { key: "prr", label: "PRR", numeric: true },
        { key: "ic025", label: "IC025", numeric: true },
        { key: "eb05", label: "EB05", numeric: true },
        { key: "methods", label: tr("Métodos", "Methods"), numeric: true },
        { key: "signal", label: tr("Regla elegida", "Chosen rule") },
        { key: "pipeline", label: tr("Preespecificada", "Prespecified") },
        { key: "kind", label: tr("Reacción", "Reaction") },
      ],
      rows: rows.map(({ r, e }) => ({
        event: label(String(r.event)),
        a: fmt(r.a, lang),
        expected: fmt(r.expected, lang, 1),
        ror: isSuppressed(r.a) ? "—" : fmtCI(r.ror, r.ror_lo, r.ror_hi, lang),
        prr: fmt(r.prr, lang, 2),
        ic025: fmt(r.ic025, lang, 2),
        eb05: fmt(r.eb05, lang, 2),
        methods: e && !e.withheld ? `${e.methods}/4` : "—",
        signal: e?.signal ? <Badge kind="on">{tr("Señal", "Signal")}</Badge> : "—",
        pipeline: e?.pipelineSignal ? <Badge kind="on">{tr("Sí", "Yes")}</Badge> : "—",
        kind: exp(String(r.event)) ? tr("esperada", "expected") : tr("no descrita", "not described"),
      })),
      csvRows: rows.map(({ r, e }) => ({
        event: label(String(r.event)),
        a: String(r.a ?? ""),
        expected: fmt(r.expected, "en", 2),
        ror: isSuppressed(r.a) ? "" : fmtCI(r.ror, r.ror_lo, r.ror_hi, "en"),
        prr: fmt(r.prr, "en", 2),
        ic025: fmt(r.ic025, "en", 3),
        eb05: fmt(r.eb05, "en", 3),
        methods: e && !e.withheld ? e.methods : "",
        signal: e?.signal ? "1" : "0",
        pipeline: e?.pipelineSignal ? "1" : "0",
        kind: exp(String(r.event)) ? "expected" : "not described",
      })),
    };
  }, [designRows, evaluated, onlySignals, lang, tr, bundle]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Cumulative IC small multiples ----------------------------------------------------------
  const cum = table(bundle, "p1_cumulative_ic");
  const cumEvents = useMemo(() => [...new Set(cum.map((r) => String(r.event)))], [cum]);
  const cumRange = useMemo(() => {
    const v = cum.flatMap((r) => [num(r.ic025), num(r.ic975)]).filter(Number.isFinite);
    return v.length ? { min: Math.floor(Math.min(0, ...v) * 2) / 2, max: Math.ceil(Math.max(...v) * 2) / 2 } : { min: -1, max: 1 };
  }, [cum]);

  // ---- Event profile ----------------------------------------------------------------------------
  const freq = table(bundle, "p1_event_frequency");
  const target = bundle.meta.target_vaccine;
  const freqData = useMemo(() => {
    const tg = freq.filter((r) => r.group === target && Number.isFinite(num(r.pct)));
    const top = tg.sort((a, b) => num(b.pct) - num(a.pct)).slice(0, 12);
    const other = (ev: unknown) => freq.find((r) => r.event === ev && r.group !== target);
    return {
      categories: top.map((r) => label(String(r.event))),
      target: top.map((r) => num(r.pct)),
      other: top.map((r) => num(other(r.event)?.pct)),
    };
  }, [freq, target, lang]); // eslint-disable-line react-hooks/exhaustive-deps
  const freqOption = useMemo(
    () =>
      bars(t, lang, {
        categories: freqData.categories,
        horizontal: true,
        digits: 1,
        suffix: lang === "es" ? " %" : "%",
        series: [
          { name: "VA-MENGOC-BC", color: t.s1, values: freqData.target },
          { name: tr("Otras vacunas", "Other vaccines"), color: t.s2, values: freqData.other },
        ],
      }),
    [t, lang, freqData, tr],
  );

  // ---- Latent classes ----------------------------------------------------------------------------
  const profiles = table(bundle, "p1_lca_profiles");
  const lcaData = useMemo(() => {
    const classes = [...new Set(profiles.map((r) => num(r.class)))].sort((a, b) => a - b);
    const items = [...new Set(profiles.map((r) => String(r.item)))];
    const weight = (c: number) => num(profiles.find((r) => num(r.class) === c)?.class_weight);
    return {
      y: classes.map((c) => `${tr("Clase", "Class")} ${c} (${fmtPct(weight(c) * 100, lang, 0)})`),
      x: items.map((i) => label(i)),
      cells: profiles.map(
        (r) =>
          [items.indexOf(String(r.item)), classes.indexOf(num(r.class)), num(r.probability) * 100] as [number, number, number],
      ),
    };
  }, [profiles, lang, tr]); // eslint-disable-line react-hooks/exhaustive-deps
  const lcaOption = useMemo(
    () =>
      heatmap(t, lang, {
        x: lcaData.x,
        y: lcaData.y,
        cells: lcaData.cells,
        min: 0,
        max: 100,
        digits: 1,
        valueLabel: tr("Probabilidad del evento en la clase (%)", "Probability of the event in the class (%)"),
      }),
    [t, lang, lcaData, tr],
  );

  // ---- Hospitalisation model ----------------------------------------------------------------------
  const logit = table(bundle, "p1_seriousness_logistic");
  const metrics = object<SeriousnessMetrics>(bundle, "p1_seriousness_metrics");
  const orData = useMemo(() => {
    const rows = logit.filter((r) => Number.isFinite(num(r.or)) && num(r.or) > 0).sort((a, b) => num(b.or) - num(a.or));
    return {
      categories: rows.map((r) => termLabel(bundle, String(r.term), lang)),
      points: rows.map((r, i) => ({
        cat: i,
        est: num(r.or),
        lo: num(r.or_lo),
        hi: num(r.or_hi),
        tip: [`p = ${fmtP(r.p_value, lang)}`],
      })),
    };
  }, [logit, bundle, lang]);
  const orOption = useMemo(
    () =>
      forest(t, lang, {
        categories: orData.categories,
        series: [{ name: tr("OR ajustada (Firth)", "Adjusted OR (Firth)"), color: t.s1, points: orData.points }],
        log: true,
        ref: 1,
        refLabel: "1",
        xName: tr("Odds ratio de hospitalización (IC 95 %)", "Odds ratio of hospitalisation (95% CI)"),
      }),
    [t, lang, orData, tr],
  );
  const shap = useMemo(
    () =>
      table(bundle, "p1_shap_importance")
        .filter((r) => Number.isFinite(num(r.mean_abs_shap)))
        .sort((a, b) => num(b.mean_abs_shap) - num(a.mean_abs_shap))
        .slice(0, 10),
    [bundle],
  );
  const shapOption = useMemo(
    () =>
      bars(t, lang, {
        categories: shap.map((r) => termLabel(bundle, String(r.feature), lang)),
        horizontal: true,
        digits: 3,
        series: [{ name: tr("|SHAP| medio", "Mean |SHAP|"), color: t.s1, values: shap.map((r) => num(r.mean_abs_shap)) }],
      }),
    [t, lang, shap, bundle, tr],
  );

  const trend = s.trend;
  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{tr("Artículo 1 · Drug Safety", "Paper 1 · Drug Safety")}</div>
        <h1>{tr("Seguridad poscomercialización", "Post-marketing safety")}</h1>
        <p className="lede">
          {tr(
            "Notificaciones espontáneas de eventos adversos supuestamente atribuibles a la vacunación (ESAVI) en Cuba. La desproporcionalidad genera hipótesis; no estima riesgos.",
            "Spontaneous reports of adverse events following immunisation (AEFI) in Cuba. Disproportionality generates hypotheses; it does not estimate risks.",
          )}
        </p>
      </header>

      <div className="filters" role="group" aria-label={tr("Filtros del análisis", "Analysis filters")}>
        <label className="field">
          {tr("Diseño comparador", "Comparator design")}
          <select value={design} onChange={(e) => setDesign(e.target.value)}>
            {designs.map((d) => (
              <option key={d} value={d}>
                {pick(DESIGN_LABELS[d], lang, d)}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <span id="crit-label">{tr("Regla de señal", "Signal rule")}</span>
          <div className="seg" role="group" aria-labelledby="crit-label">
            {CRITERIA.map((c) => (
              <button
                key={c.value}
                type="button"
                aria-pressed={criterion === c.value}
                title={lang === "es" ? c.es : c.en}
                onClick={() => setCriterion(c.value)}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
        <label className="field">
          {tr(`Mínimo de notificaciones: ${minReports}`, `Minimum reports: ${minReports}`)}
          <input type="range" min={1} max={20} value={minReports} onChange={(e) => setMinReports(Number(e.target.value))} />
        </label>
        <label className="check">
          <input type="checkbox" checked={onlySignals} onChange={(e) => setOnlySignals(e.target.checked)} />
          {tr("Solo señales", "Signals only")}
        </label>
      </div>

      <div className="kpis">
        <StatTile
          label={tr("Notificaciones con VA-MENGOC-BC", "Reports with VA-MENGOC-BC")}
          value={fmt(s.targetReports, lang)}
          sub={tr(`de ${fmt(s.allReports, lang)} en total`, `of ${fmt(s.allReports, lang)} in total`)}
        />
        <StatTile
          label={tr("Tasa conjunta por 100 000 dosis", "Pooled rate per 100,000 doses")}
          value={fmt(trend.pooled_rate_per_100k, lang, 1)}
          sub={`${tr("IC 95 %", "95% CI")} ${fmt(trend.pooled_rate_lo, lang, 1)}–${fmt(trend.pooled_rate_hi, lang, 1)}`}
        />
        <StatTile
          label={tr("Razón de tasas anual", "Annual rate ratio")}
          value={fmt(trend.rr_per_year, lang, 3)}
          sub={`${tr("IC 95 %", "95% CI")} ${fmt(trend.rr_lo, lang, 3)}–${fmt(trend.rr_hi, lang, 3)}`}
        />
        <StatTile
          label={tr("Señales con la regla elegida", "Signals under the chosen rule")}
          value={fmt(nSignals, lang)}
          sub={tr(
            `preespecificadas: ${nPipeline}; concordancia ${agree}/${comparable}`,
            `prespecified: ${nPipeline}; agreement ${agree}/${comparable}`,
          )}
        />
      </div>

      <SectionTitle title={tr("Notificación a lo largo del tiempo", "Reporting over time")} />
      <div className="grid two">
        <Figure
          title={tr("Tasa de notificación por año", "Reporting rate by year")}
          subtitle={tr("Notificaciones por 100 000 dosis administradas, IC 95 % exacto de Poisson", "Reports per 100,000 doses administered, exact Poisson 95% CI")}
          legend={
            <Legend
              items={[
                { label: tr("Tasa", "Rate"), color: t.s1, shape: "line" },
                { label: tr("IC 95 %", "95% CI"), color: t.band2, shape: "band" },
              ]}
            />
          }
          csvName="p1_rates_target"
          table={{
            columns: [
              { key: "year", label: tr("Año", "Year") },
              { key: "count", label: tr("Notificaciones", "Reports"), numeric: true },
              { key: "doses", label: tr("Dosis", "Doses"), numeric: true },
              { key: "rate", label: tr("Tasa (IC 95 %)", "Rate (95% CI)"), numeric: true },
            ],
            rows: rates.map((r) => ({
              year: String(r.year),
              count: fmt(r.count, lang),
              doses: fmt(r.doses, lang),
              rate: fmtCI(r.rate_per_100k, r.rate_lo, r.rate_hi, lang, 1),
            })),
          }}
        >
          <Chart option={rateOption} height={300} label={tr("Tasa de notificación por año con intervalo de confianza", "Reporting rate by year with confidence interval")} />
        </Figure>
        <Figure
          title={tr("Notificaciones mensuales y puntos de cambio", "Monthly reports and change points")}
          subtitle={tr(
            `Segmentos detectados por PELT: ${cps?.breaks.join(", ") || "ninguno"}`,
            `Segments detected by PELT: ${cps?.breaks.join(", ") || "none"}`,
          )}
          legend={
            <Legend
              items={[
                { label: tr("Notificaciones mensuales", "Monthly reports"), color: t.s1 },
                { label: tr("Media del segmento", "Segment mean"), color: t.s2 },
              ]}
            />
          }
          csvName="p1_monthly_target"
          table={{
            columns: [
              { key: "month", label: tr("Mes", "Month") },
              { key: "count", label: tr("Notificaciones", "Reports"), numeric: true },
            ],
            rows: monthly.map((r) => ({ month: String(r.month), count: fmt(r.count, lang) })),
          }}
        >
          <Chart option={monthlyOption} height={300} label={tr("Serie mensual de notificaciones", "Monthly series of reports")} />
        </Figure>
      </div>

      <SectionTitle
        title={tr("Desproporcionalidad", "Disproportionality")}
        sub={
          sizes
            ? tr(
                `${pick(DESIGN_LABELS[design], lang, design)}: ${fmt(sizes.n_target, lang)} notificaciones de la vacuna frente a ${fmt(sizes.n_comparator, lang)} del comparador`,
                `${pick(DESIGN_LABELS[design], lang, design)}: ${fmt(sizes.n_target, lang)} vaccine reports versus ${fmt(sizes.n_comparator, lang)} comparator reports`,
              )
            : undefined
        }
      />
      <Figure
        title={tr("Medida de desproporcionalidad por evento", "Disproportionality measure by event")}
        subtitle={tr(
          `${measureName}; regla: ${CRITERIA.find((c) => c.value === criterion)?.es ?? ""}, a ≥ ${minReports}`,
          `${measureName}; rule: ${CRITERIA.find((c) => c.value === criterion)?.en ?? ""}, a ≥ ${minReports}`,
        )}
        legend={
          <Legend
            items={[
              { label: tr("Señal con la regla elegida", "Signal under the chosen rule"), color: t.s1, shape: "dot" },
              { label: tr("Sin señal", "No signal"), color: t.deemph, shape: "dot" },
            ]}
          />
        }
        table={dpTable}
        csvName={`p1_disproportionality_${design}`}
        note={tr(
          "La aplicación no recalcula medidas: aplica otra regla de decisión a las medidas publicadas. Las celdas suprimidas (<5, [c]) no se muestran en el gráfico.",
          "The app does not recompute measures: it applies another decision rule to the released measures. Suppressed cells (<5, [c]) are not plotted.",
        )}
      >
        <Chart
          option={forestOption}
          height={forestHeight(forestData.categories.length)}
          label={tr("Gráfico de bosque de la desproporcionalidad por evento", "Forest plot of disproportionality by event")}
        />
      </Figure>

      <div style={{ height: 16 }} />
      <Figure
        title={tr("Evolución acumulada del IC", "Cumulative IC over time")}
        subtitle={tr(
          "IC calculado con los datos acumulados hasta cada año (diseño principal); banda IC025–IC975",
          "IC computed on data accumulated up to each year (primary design); band IC025–IC975",
        )}
        legend={
          <Legend
            items={[
              { label: "IC", color: t.s1 },
              { label: "IC025–IC975", color: t.band2, shape: "band" },
            ]}
          />
        }
        csvName="p1_cumulative_ic"
        table={{
          columns: [
            { key: "event", label: tr("Evento", "Event") },
            { key: "year", label: tr("Año", "Year") },
            { key: "a", label: "a", numeric: true },
            { key: "ic", label: "IC (IC025–IC975)", numeric: true },
          ],
          rows: cum.map((r) => ({
            event: label(String(r.event)),
            year: String(r.year),
            a: fmt(r.a, lang),
            ic: fmtCI(r.ic, r.ic025, r.ic975, lang),
          })),
        }}
      >
        <div className="multiples">
          {cumEvents.map((ev) => {
            const rows = cum.filter((r) => r.event === ev);
            const any = rows.some((r) => Number.isFinite(num(r.ic)));
            return (
              <div key={ev}>
                <h4>{label(ev)}</h4>
                {any ? (
                  <Chart
                    height={150}
                    label={tr(`IC acumulado: ${label(ev)}`, `Cumulative IC: ${label(ev)}`)}
                    option={bandLine(t, lang, {
                      x: rows.map((r) => String(r.year)),
                      y: rows.map((r) => num(r.ic)),
                      lo: rows.map((r) => num(r.ic025)),
                      hi: rows.map((r) => num(r.ic975)),
                      name: "IC",
                      bandLabel: "IC025–IC975",
                      digits: 2,
                      refs: [{ value: 0, label: "" }],
                      yMin: cumRange.min,
                      yMax: cumRange.max,
                    })}
                  />
                ) : (
                  <p className="card-note" style={{ height: 150, display: "grid", placeItems: "center", textAlign: "center" }}>
                    {tr("Recuentos anuales suprimidos por control de divulgación", "Annual counts suppressed by disclosure control")}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </Figure>

      <SectionTitle title={tr("Perfil de eventos y fenotipos", "Event profile and phenotypes")} />
      <div className="grid two">
        <Figure
          title={tr("Eventos más frecuentes", "Most frequent events")}
          subtitle={tr("Porcentaje de notificaciones que incluyen cada evento", "Percentage of reports that include each event")}
          legend={
            <Legend
              items={[
                { label: "VA-MENGOC-BC", color: t.s1, shape: "rect" },
                { label: tr("Otras vacunas", "Other vaccines"), color: t.s2, shape: "rect" },
              ]}
            />
          }
          csvName="p1_event_frequency"
          table={{
            columns: [
              { key: "event", label: tr("Evento", "Event") },
              { key: "t", label: "VA-MENGOC-BC", numeric: true },
              { key: "o", label: tr("Otras vacunas", "Other vaccines"), numeric: true },
            ],
            rows: freqData.categories.map((c, i) => ({
              event: c,
              t: fmtPct(freqData.target[i], lang),
              o: fmtPct(freqData.other[i], lang),
            })),
          }}
        >
          <Chart option={freqOption} height={barsHeight(freqData.categories.length, 2)} label={tr("Frecuencia de eventos", "Event frequency")} />
        </Figure>
        <Figure
          title={tr("Fenotipos latentes de notificación", "Latent reporting phenotypes")}
          subtitle={tr(
            `${s.bestK ?? "—"} clases seleccionadas por BIC; estabilidad bootstrap (ARI mediano) ${fmt(s.ari, lang, 2)}`,
            `${s.bestK ?? "—"} classes selected by BIC; bootstrap stability (median ARI) ${fmt(s.ari, lang, 2)}`,
          )}
          csvName="p1_lca_profiles"
          table={{
            columns: [
              { key: "cls", label: tr("Clase", "Class") },
              { key: "item", label: tr("Evento", "Event") },
              { key: "p", label: tr("Probabilidad", "Probability"), numeric: true },
            ],
            rows: profiles.map((r) => ({ cls: String(r.class), item: label(String(r.item)), p: fmtPct(num(r.probability) * 100, lang) })),
          }}
        >
          <Chart option={lcaOption} height={360} label={tr("Mapa de calor de perfiles de clase latente", "Heat map of latent class profiles")} />
        </Figure>
      </div>

      <SectionTitle
        title={tr("Hospitalización notificada", "Reported hospitalisation")}
        sub={
          metrics
            ? tr(
                `Validación temporal: AUROC ${fmt(metrics.metrics.logistic_test?.auroc, lang, 2)} (logística de Firth) y ${fmt(metrics.metrics.gbm_test?.auroc, lang, 2)} (gradient boosting)`,
                `Temporal validation: AUROC ${fmt(metrics.metrics.logistic_test?.auroc, lang, 2)} (Firth logistic) and ${fmt(metrics.metrics.gbm_test?.auroc, lang, 2)} (gradient boosting)`,
              )
            : undefined
        }
      />
      <div className="grid two">
        <Figure
          title={tr("Factores asociados a la hospitalización", "Factors associated with hospitalisation")}
          subtitle={tr("Regresión logística penalizada de Firth, todas las vacunas", "Firth penalised logistic regression, all vaccines")}
          csvName="p1_seriousness_logistic"
          table={{
            columns: [
              { key: "term", label: tr("Término", "Term") },
              { key: "or", label: tr("OR (IC 95 %)", "OR (95% CI)"), numeric: true },
              { key: "p", label: "p", numeric: true },
            ],
            rows: logit.map((r) => ({
              term: termLabel(bundle, String(r.term), lang),
              or: fmtCI(r.or, r.or_lo, r.or_hi, lang),
              p: fmtP(r.p_value, lang),
            })),
          }}
        >
          <Chart option={orOption} height={forestHeight(orData.categories.length)} label={tr("Odds ratios del modelo de hospitalización", "Odds ratios of the hospitalisation model")} />
        </Figure>
        <Figure
          title={tr("Importancia de las variables", "Feature importance")}
          subtitle={tr("Media del valor SHAP absoluto en el modelo de gradient boosting", "Mean absolute SHAP value in the gradient boosting model")}
          csvName="p1_shap_importance"
          table={{
            columns: [
              { key: "f", label: tr("Variable", "Feature") },
              { key: "v", label: tr("|SHAP| medio", "Mean |SHAP|"), numeric: true },
            ],
            rows: shap.map((r) => ({ f: termLabel(bundle, String(r.feature), lang), v: fmt(r.mean_abs_shap, lang, 3) })),
          }}
        >
          <Chart option={shapOption} height={barsHeight(shap.length)} label={tr("Importancia SHAP", "SHAP importance")} />
        </Figure>
      </div>
    </>
  );
}
