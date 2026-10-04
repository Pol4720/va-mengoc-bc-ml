// Paper 2: process quality of the released lots and the case-only association between lot
// attributes and reactogenicity. Lot values are shown only on the normalised window scale.

import { useMemo, useState } from "react";
import { bars, barsHeight, controlChart, fan, forest, forestHeight, heatmap, lines } from "../charts/builders";
import { Chart } from "../components/Chart";
import { Badge, Figure, Legend, SectionTitle, StatTile, type TableData } from "../components/ui";
import { bool, num, object, table, type Row } from "../data/bundle";
import { fmt, fmtCI, fmtP, fmtPct } from "../data/format";
import { FDR_ALPHA, p2Summary } from "../data/summary";
import { SENSITIVITY_LABELS, attributeLabel, outcomeLabel, pick, useLang } from "../i18n";
import { useBundle } from "../state";
import { useTokens } from "../theme";

const PERIOD_ALL = "all";

export function LotQuality() {
  const { bundle } = useBundle();
  const { lang, tr } = useLang();
  const t = useTokens();
  const s = useMemo(() => p2Summary(bundle), [bundle]);
  const series = table(bundle, "p2_lot_series");
  const attributes = useMemo(() => [...new Set(series.map((r) => String(r.attribute)))], [series]);
  const gee = table(bundle, "p2_gee_primary");
  const outcomes = useMemo(() => [...new Set(gee.map((r) => String(r.outcome)))], [gee]);
  const [attribute, setAttribute] = useState(() => (attributes.includes("endotoxin") ? "endotoxin" : (attributes[0] ?? "")));
  const [outcome, setOutcome] = useState(() => outcomes[0] ?? "");
  const aLabel = (a: string) => attributeLabel(bundle, a, lang);
  const oLabel = (o: string) => outcomeLabel(bundle, o, lang);

  // ---- Capability -----------------------------------------------------------------------------
  const cap = table(bundle, "p2_capability");
  const capData = useMemo(() => {
    const est = cap.filter((r) => bool(r.estimable));
    const periods = [...new Set(est.map((r) => String(r.period)))].filter((p) => p !== PERIOD_ALL).sort();
    const attrs = [...new Set(est.map((r) => String(r.attribute)))];
    const colors = [t.s1, t.s2, t.s3];
    return {
      categories: attrs.map((a) => attributeLabel(bundle, a, lang)),
      periods,
      series: periods.map((p, pi) => ({
        name: p.replace("-", "–"),
        color: colors[pi] ?? t.s1,
        points: est
          .filter((r) => r.period === p)
          .map((r) => ({
            cat: attrs.indexOf(String(r.attribute)),
            est: num(r.ppk),
            lo: num(r.ppk_lo),
            hi: num(r.ppk_hi),
            tip: [
              `n = ${fmt(r.n, lang)}`,
              tr(`conformes ${fmtPct(r.pct_conforming, lang)}`, `conforming ${fmtPct(r.pct_conforming, lang)}`),
            ],
          })),
      })),
      rows: est,
    };
  }, [cap, t, bundle, lang, tr]);
  const capOption = useMemo(
    () =>
      forest(t, lang, {
        categories: capData.categories,
        series: capData.series,
        ref: 1,
        refLabel: fmt(1, lang, 2),
        extraRefs: [{ value: 1.33, label: fmt(1.33, lang, 2) }],
        xName: tr("Ppk (IC 95 %)", "Ppk (95% CI)"),
      }),
    [t, lang, capData, tr],
  );

  // ---- Selected attribute: annual quantiles, control chart, EWMA ---------------------------------
  const quant = table(bundle, "p2_qc_annual_quantiles");
  const q = useMemo(
    () => quant.filter((r) => r.attribute === attribute).sort((a, b) => num(a.production_year) - num(b.production_year)),
    [quant, attribute],
  );
  const fanOption = useMemo(
    () =>
      fan(t, lang, {
        x: q.map((r) => String(r.production_year)),
        q10: q.map((r) => num(r.q10)),
        q25: q.map((r) => num(r.q25)),
        q50: q.map((r) => num(r.q50)),
        q75: q.map((r) => num(r.q75)),
        q90: q.map((r) => num(r.q90)),
        n: q.map((r) => num(r.n_lots)),
        labels: {
          median: tr("Mediana", "Median"),
          inner: tr("Percentiles 25–75", "25th–75th percentile"),
          outer: tr("Percentiles 10–90", "10th–90th percentile"),
          n: tr("Lotes", "Lots"),
        },
        refs: [
          { value: 0, label: tr("límite inferior", "lower limit") },
          { value: 1, label: tr("límite superior", "upper limit") },
        ],
      }),
    [t, lang, q, tr],
  );
  const ser = useMemo(() => series.filter((r) => r.attribute === attribute), [series, attribute]);
  const flags = useMemo(() => ser.map((r) => bool(r.rule1)), [ser]);
  const ctlOption = useMemo(
    () =>
      controlChart(t, lang, {
        seq: ser.map((r) => num(r.seq)),
        values: ser.map((r) => num(r.z)),
        flagged: flags,
        years: ser.map((r) => num(r.production_year)),
        name: tr("Valor estandarizado (z)", "Standardised value (z)"),
        flaggedName: tr("Fuera de control (|z| > 3)", "Out of control (|z| > 3)"),
        yName: "z",
        limits: [
          { value: 3, label: "+3σ" },
          { value: -3, label: "−3σ" },
        ],
        lotLabel: tr("Lote", "Lot"),
        yearLabel: tr("año", "year"),
      }),
    [t, lang, ser, flags, tr],
  );
  const ewmaFlags = useMemo(() => ser.map((r) => bool(r.ewma_signal)), [ser]);
  const ewmaOption = useMemo(
    () =>
      controlChart(t, lang, {
        seq: ser.map((r) => num(r.seq)),
        values: ser.map((r) => num(r.ewma_window)),
        flagged: ewmaFlags,
        years: ser.map((r) => num(r.production_year)),
        ucl: ser.map((r) => num(r.ewma_ucl_window)),
        lcl: ser.map((r) => num(r.ewma_lcl_window)),
        name: "EWMA",
        flaggedName: tr("Señal EWMA", "EWMA signal"),
        limitName: tr("Límites de control", "Control limits"),
        yName: tr("posición en la ventana", "window position"),
        lotLabel: tr("Lote", "Lot"),
        yearLabel: tr("año", "year"),
      }),
    [t, lang, ser, ewmaFlags, tr],
  );
  const nRule1 = flags.filter(Boolean).length;
  const nEwma = ewmaFlags.filter(Boolean).length;
  const changepoints = table(bundle, "p2_changepoints").filter((r) => r.attribute === attribute);

  // ---- Multivariate ------------------------------------------------------------------------------
  const t2 = table(bundle, "p2_mspc_t2_quantiles");
  const mspc = object<{ t2_limit?: number; n_flagged?: number; n_lots?: number }>(bundle, "p2_mspc_summary");
  const t2Option = useMemo(
    () =>
      lines(t, lang, {
        x: t2.map((r) => String(r.production_year)),
        series: [
          { name: tr("Mediana de T²", "Median T²"), color: t.s1, values: t2.map((r) => num(r.q50)), symbol: true },
          { name: tr("Percentil 90 de T²", "90th percentile of T²"), color: t.s2, values: t2.map((r) => num(r.q90)), symbol: true },
        ],
        digits: 1,
        yMin: 0,
        refs: mspc?.t2_limit ? [{ value: mspc.t2_limit, label: tr("límite T² (99 %)", "T² limit (99%)") }] : undefined,
      }),
    [t, lang, t2, mspc, tr],
  );
  const corr = table(bundle, "p2_attribute_correlation");
  const corrOption = useMemo(() => {
    const attrs = corr.map((r) => String(r.attribute));
    const labels = attrs.map((a) => attributeLabel(bundle, a, lang));
    const cells: [number, number, number | null][] = [];
    corr.forEach((r, yi) => attrs.forEach((a, xi) => cells.push([xi, yi, num(r[a])])));
    return heatmap(t, lang, {
      x: labels,
      y: labels,
      cells,
      min: -1,
      max: 1,
      diverging: true,
      digits: 2,
      valueLabel: tr("Correlación de Spearman", "Spearman correlation"),
    });
  }, [corr, bundle, lang, t, tr]);

  // ---- Equivalence national vs export --------------------------------------------------------------
  const eq = table(bundle, "p2_equivalence");
  const eqOption = useMemo(() => {
    const rows = eq.filter((r) => bool(r.estimable));
    const margin = num(rows[0]?.margin);
    return forest(t, lang, {
      categories: rows.map((r) => attributeLabel(bundle, String(r.attribute), lang)),
      series: [
        {
          name: tr("Diferencia (IC 90 %)", "Difference (90% CI)"),
          color: t.s1,
          points: rows.map((r, i) => ({
            cat: i,
            est: num(r.diff),
            lo: num(r.ci90_lo),
            hi: num(r.ci90_hi),
            tip: [`p TOST = ${fmtP(r.p_tost, lang)}`],
          })),
        },
      ],
      ref: 0,
      refLabel: "0",
      band: Number.isFinite(margin) ? { from: -margin, to: margin, label: tr("margen de equivalencia", "equivalence margin") } : undefined,
      xName: tr("Diferencia en posición de ventana (nacional − exportación)", "Difference in window position (national − export)"),
      digits: 3,
    });
  }, [eq, bundle, lang, t, tr]);

  // ---- Linkage ---------------------------------------------------------------------------------------
  const lby = table(bundle, "p2_linkage_by_year");
  const linkOption = useMemo(
    () =>
      bars(t, lang, {
        categories: lby.map((r) => String(r.analytic_year)),
        series: [
          {
            name: tr("Notificaciones enlazadas", "Linked reports"),
            color: t.s1,
            values: lby.map((r) => (num(r.n_reports) > 0 ? (num(r.n_linked) / num(r.n_reports)) * 100 : null)),
          },
        ],
        digits: 1,
        suffix: lang === "es" ? " %" : "%",
        max: 100,
      }),
    [t, lang, lby, tr],
  );
  const bias = table(bundle, "p2_linkage_bias");

  // ---- Associations ----------------------------------------------------------------------------------
  const mdeRow = table(bundle, "p2_mde").find((r) => r.outcome === outcome);
  const mde = num(mdeRow?.mde_or_per_sd);
  const assoc = useMemo(() => {
    const rows = gee.filter((r) => r.outcome === outcome);
    const exposures = [...new Set(rows.map((r) => String(r.exposure)))];
    const cats = exposures.map((e) => {
      const nc = rows.some((r) => r.exposure === e && bool(r.negative_control));
      return `${attributeLabel(bundle, e, lang)}${nc ? tr(" (control negativo)", " (negative control)") : ""}`;
    });
    const pts = (model: string) =>
      rows
        .filter((r) => r.model === model)
        .map((r) => ({
          cat: exposures.indexOf(String(r.exposure)),
          est: num(r.or_per_sd),
          lo: num(r.or_lo),
          hi: num(r.or_hi),
          tip: [`p = ${fmtP(r.p_value, lang)}`, Number.isFinite(num(r.p_bh)) ? `q = ${fmtP(r.p_bh, lang)}` : ""].filter(Boolean),
        }));
    return { rows, cats, adjusted: pts("single"), crude: pts("crude"), mutual: pts("mutually_adjusted") };
  }, [gee, outcome, bundle, lang, tr]);
  const assocOption = useMemo(
    () =>
      forest(t, lang, {
        categories: assoc.cats,
        series: [
          { name: tr("Ajustada", "Adjusted"), color: t.s1, points: assoc.adjusted },
          { name: tr("Cruda", "Crude"), color: t.s2, points: assoc.crude },
        ],
        log: true,
        ref: 1,
        refLabel: "1",
        band: Number.isFinite(mde) ? { from: 1 / mde, to: mde, label: tr("bajo el efecto mínimo detectable", "below the minimum detectable effect") } : undefined,
        xName: tr("OR por DE del atributo (IC 95 %)", "OR per SD of the attribute (95% CI)"),
      }),
    [t, lang, assoc, mde, tr],
  );
  const assocTable: TableData = useMemo(
    () => ({
      columns: [
        { key: "exp", label: tr("Atributo", "Attribute") },
        { key: "model", label: tr("Modelo", "Model") },
        { key: "or", label: tr("OR por DE (IC 95 %)", "OR per SD (95% CI)"), numeric: true },
        { key: "p", label: "p", numeric: true },
        { key: "q", label: "q (BH)", numeric: true },
        { key: "n", label: "n", numeric: true },
        { key: "lots", label: tr("Lotes", "Lots"), numeric: true },
      ],
      rows: assoc.rows.map((r: Row) => ({
        exp: attributeLabel(bundle, String(r.exposure), lang),
        model:
          r.model === "single"
            ? tr("ajustado", "adjusted")
            : r.model === "crude"
              ? tr("crudo", "crude")
              : tr("mutuamente ajustado", "mutually adjusted"),
        or: fmtCI(r.or_per_sd, r.or_lo, r.or_hi, lang),
        p: fmtP(r.p_value, lang),
        q: Number.isFinite(num(r.p_bh)) ? (
          num(r.p_bh) < FDR_ALPHA ? <Badge kind="on">{fmtP(r.p_bh, lang)}</Badge> : fmtP(r.p_bh, lang)
        ) : (
          "—"
        ),
        n: fmt(r.n, lang),
        lots: fmt(r.n_lots, lang),
      })),
      csvRows: assoc.rows.map((r: Row) => ({
        exp: String(r.exposure),
        model: String(r.model),
        or: fmtCI(r.or_per_sd, r.or_lo, r.or_hi, "en", 3),
        p: String(r.p_value ?? ""),
        q: String(r.p_bh ?? ""),
        n: String(r.n ?? ""),
        lots: String(r.n_lots ?? ""),
      })),
    }),
    [assoc, bundle, lang, tr],
  );

  // ---- Sensitivity for the selected pair ---------------------------------------------------------------
  const sens = useMemo(() => {
    const prim = gee.find((r) => r.outcome === outcome && r.exposure === attribute && r.model === "single");
    if (!prim) return null;
    const pick2 = (key: string, r: Row | undefined, est = "or_per_sd", lo = "or_lo", hi = "or_hi") =>
      r ? { key, est: num(r[est]), lo: num(r[lo]), hi: num(r[hi]) } : null;
    const sensRows = table(bundle, "p2_gee_sensitivity").filter(
      (r) => r.outcome === outcome && r.exposure === attribute && r.model === "single",
    );
    const items = [
      pick2("primary", prim),
      ...sensRows.map((r) => pick2(String(r.sensitivity), r)),
      pick2(
        "mixed",
        table(bundle, "p2_mixed_model").find((r) => r.outcome === outcome && r.exposure === attribute),
        "or_per_sd",
        "cri_lo",
        "cri_hi",
      ),
      pick2("lot_level", table(bundle, "p2_lot_level").find((r) => r.outcome === outcome && r.exposure === attribute)),
    ].filter((x): x is { key: string; est: number; lo: number; hi: number } => !!x && Number.isFinite(x.est));
    return items;
  }, [gee, bundle, outcome, attribute]);
  const sensOption = useMemo(
    () =>
      sens
        ? forest(t, lang, {
            categories: sens.map((x) => pick(SENSITIVITY_LABELS[x.key], lang, x.key)),
            series: [
              {
                name: tr("OR por DE", "OR per SD"),
                color: t.s1,
                points: sens.map((x, i) => ({ cat: i, est: x.est, lo: x.lo, hi: x.hi })),
              },
            ],
            log: true,
            ref: 1,
            refLabel: "1",
            xName: tr("OR por DE (intervalo 95 %)", "OR per SD (95% interval)"),
          })
        : null,
    [sens, t, lang, tr],
  );

  const inc = table(bundle, "p2_incremental_value");

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{tr("Artículo 2 · Vaccine", "Paper 2 · Vaccine")}</div>
        <h1>{tr("Atributos de liberación de lotes y reactogenicidad", "Lot release attributes and reactogenicity")}</h1>
        <p className="lede">
          {tr(
            "¿Se asocia la variación dentro de especificación de los atributos de calidad con el perfil de las notificaciones? Diseño de solo casos con errores robustos agrupados por lote. Los valores se muestran en la escala normalizada de la ventana de referencia (0 = límite inferior, 1 = límite superior).",
            "Is within-specification variation of quality attributes associated with the profile of the reports? Case-only design with lot-clustered robust errors. Values are shown on the normalised reference-window scale (0 = lower limit, 1 = upper limit).",
          )}
        </p>
      </header>

      <div className="filters" role="group" aria-label={tr("Filtros del análisis", "Analysis filters")}>
        <label className="field">
          {tr("Atributo de calidad", "Quality attribute")}
          <select value={attribute} onChange={(e) => setAttribute(e.target.value)}>
            {attributes.map((a) => (
              <option key={a} value={a}>
                {aLabel(a)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          {tr("Reacción", "Reaction")}
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            {outcomes.map((o) => (
              <option key={o} value={o}>
                {oLabel(o)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="kpis">
        <StatTile label={tr("Lotes liberados", "Released lots")} value={fmt(s.nLots, lang)} sub={tr(`${fmt(s.lotsFlagged, lang)} atípicos multivariantes`, `${fmt(s.lotsFlagged, lang)} multivariate outliers`)} />
        <StatTile
          label={tr("Notificaciones enlazadas", "Linked reports")}
          value={fmtPct(s.linkRate * 100, lang)}
          sub={tr(`${fmt(s.nLinked, lang)} de ${fmt(s.nTargetReports, lang)}`, `${fmt(s.nLinked, lang)} of ${fmt(s.nTargetReports, lang)}`)}
        />
        <StatTile
          label={tr("Notificaciones analizadas", "Reports analysed")}
          value={fmt(s.nAnalysed, lang)}
          sub={tr(`en ${fmt(s.nLotsAnalysed, lang)} lotes`, `in ${fmt(s.nLotsAnalysed, lang)} lots`)}
        />
        <StatTile
          label={tr("Asociaciones con q < 0,05", "Associations with q < 0.05")}
          value={`${fmt(s.significant.length, lang)} / ${fmt(s.nAssociations, lang)}`}
          sub={tr("familia preespecificada, Benjamini–Hochberg", "prespecified family, Benjamini–Hochberg")}
        />
      </div>

      <SectionTitle title={tr("Calidad del proceso", "Process quality")} />
      <div className="grid two">
        <Figure
          title={tr("Capacidad de proceso por periodo", "Process capability by period")}
          subtitle={tr("Ppk con IC 95 % bootstrap; 1,00 y 1,33 como referencias habituales", "Ppk with bootstrap 95% CI; 1.00 and 1.33 as customary references")}
          legend={<Legend items={capData.series.map((x) => ({ label: x.name, color: x.color, shape: "dot" as const }))} />}
          csvName="p2_capability"
          table={{
            columns: [
              { key: "a", label: tr("Atributo", "Attribute") },
              { key: "p", label: tr("Periodo", "Period") },
              { key: "n", label: "n", numeric: true },
              { key: "ppk", label: tr("Ppk (IC 95 %)", "Ppk (95% CI)"), numeric: true },
              { key: "c", label: tr("Conformes", "Conforming"), numeric: true },
            ],
            rows: capData.rows.map((r) => ({
              a: aLabel(String(r.attribute)),
              p: r.period === PERIOD_ALL ? tr("todos", "all") : String(r.period),
              n: fmt(r.n, lang),
              ppk: fmtCI(r.ppk, r.ppk_lo, r.ppk_hi, lang),
              c: fmtPct(r.pct_conforming, lang),
            })),
          }}
        >
          <Chart option={capOption} height={forestHeight(capData.categories.length, capData.series.length)} label={tr("Capacidad de proceso por atributo", "Process capability by attribute")} />
        </Figure>
        <Figure
          title={tr(`Distribución anual: ${aLabel(attribute)}`, `Annual distribution: ${aLabel(attribute)}`)}
          subtitle={tr("Posición en la ventana de referencia por año de producción", "Position in the reference window by production year")}
          legend={
            <Legend
              items={[
                { label: tr("Mediana", "Median"), color: t.s1 },
                { label: tr("P25–P75", "P25–P75"), color: t.band2, shape: "band" },
                { label: tr("P10–P90", "P10–P90"), color: t.band, shape: "band" },
              ]}
            />
          }
          csvName={`p2_quantiles_${attribute}`}
          table={{
            columns: [
              { key: "y", label: tr("Año", "Year") },
              { key: "n", label: tr("Lotes", "Lots"), numeric: true },
              { key: "q10", label: "P10", numeric: true },
              { key: "q50", label: "P50", numeric: true },
              { key: "q90", label: "P90", numeric: true },
            ],
            rows: q.map((r) => ({
              y: String(r.production_year),
              n: fmt(r.n_lots, lang),
              q10: fmt(r.q10, lang, 2),
              q50: fmt(r.q50, lang, 2),
              q90: fmt(r.q90, lang, 2),
            })),
          }}
        >
          <Chart option={fanOption} height={320} label={tr("Cuantiles anuales del atributo", "Annual quantiles of the attribute")} />
        </Figure>
      </div>

      <div style={{ height: 16 }} />
      <Figure
        title={tr(`Gráfico de control: ${aLabel(attribute)}`, `Control chart: ${aLabel(attribute)}`)}
        subtitle={tr(
          `${fmt(nRule1, lang)} lotes fuera de ±3σ; ${changepoints.length ? `punto de cambio en ${changepoints.map((c) => c.production_year).join(", ")}` : "sin puntos de cambio"}. Arrastre o use la rueda para recorrer la secuencia.`,
          `${fmt(nRule1, lang)} lots outside ±3σ; ${changepoints.length ? `change point in ${changepoints.map((c) => c.production_year).join(", ")}` : "no change points"}. Drag or scroll to move along the sequence.`,
        )}
        legend={
          <Legend
            items={[
              { label: tr("Valor estandarizado (z)", "Standardised value (z)"), color: t.s1 },
              { label: tr("Fuera de control", "Out of control"), color: t.critical, shape: "dot" },
              { label: tr("Límites ±3σ", "±3σ limits"), color: t.muted, shape: "dashed" },
            ]}
          />
        }
      >
        <Chart option={ctlOption} height={300} label={tr("Gráfico de control de valores individuales", "Individual values control chart")} />
      </Figure>
      <div style={{ height: 16 }} />
      <Figure
        title={tr(`EWMA: ${aLabel(attribute)}`, `EWMA: ${aLabel(attribute)}`)}
        subtitle={tr(`${fmt(nEwma, lang)} lotes con señal EWMA`, `${fmt(nEwma, lang)} lots with an EWMA signal`)}
        legend={
          <Legend
            items={[
              { label: "EWMA", color: t.s1 },
              { label: tr("Señal", "Signal"), color: t.critical, shape: "dot" },
              { label: tr("Límites de control", "Control limits"), color: t.muted, shape: "dashed" },
            ]}
          />
        }
      >
        <Chart option={ewmaOption} height={260} label={tr("Gráfico EWMA", "EWMA chart")} />
      </Figure>

      <div style={{ height: 16 }} />
      <div className="grid two">
        <Figure
          title={tr("Atipicidad multivariante (T² de Hotelling)", "Multivariate atypicality (Hotelling T²)")}
          subtitle={tr(
            `${fmt(mspc?.n_flagged, lang)} de ${fmt(mspc?.n_lots, lang)} lotes por encima de los límites T² o SPE`,
            `${fmt(mspc?.n_flagged, lang)} of ${fmt(mspc?.n_lots, lang)} lots above the T² or SPE limits`,
          )}
          legend={
            <Legend
              items={[
                { label: tr("Mediana", "Median"), color: t.s1 },
                { label: tr("Percentil 90", "90th percentile"), color: t.s2 },
              ]}
            />
          }
          csvName="p2_mspc_t2_quantiles"
          table={{
            columns: [
              { key: "y", label: tr("Año", "Year") },
              { key: "n", label: tr("Lotes", "Lots"), numeric: true },
              { key: "m", label: tr("Mediana", "Median"), numeric: true },
              { key: "p90", label: "P90", numeric: true },
              { key: "f", label: tr("Sobre el límite T²", "Above T² limit"), numeric: true },
            ],
            rows: t2.map((r) => ({
              y: String(r.production_year),
              n: fmt(r.n_lots, lang),
              m: fmt(r.q50, lang, 1),
              p90: fmt(r.q90, lang, 1),
              f: fmt(r.n_t2_flagged, lang),
            })),
          }}
        >
          <Chart option={t2Option} height={300} label={tr("T² anual", "Annual T²")} />
        </Figure>
        <Figure
          title={tr("Correlación entre atributos", "Correlation between attributes")}
          subtitle={tr("Spearman, escala azul (negativa) a roja (positiva) con gris en cero", "Spearman, blue (negative) to red (positive) scale with grey at zero")}
        >
          <Chart option={corrOption} height={380} label={tr("Mapa de calor de correlaciones", "Correlation heat map")} />
        </Figure>
      </div>
      <div style={{ height: 16 }} />
      <Figure
        title={tr("Equivalencia entre lotes nacionales y de exportación", "Equivalence between national and export lots")}
        subtitle={tr("Prueba TOST: equivalentes si el IC 90 % cae dentro del margen", "TOST: equivalent when the 90% CI lies within the margin")}
        legend={
          <Legend
            items={[
              { label: tr("Diferencia (IC 90 %)", "Difference (90% CI)"), color: t.s1, shape: "dot" },
              { label: tr("Margen de equivalencia", "Equivalence margin"), color: t.band2, shape: "band" },
            ]}
          />
        }
        csvName="p2_equivalence"
        table={{
          columns: [
            { key: "a", label: tr("Atributo", "Attribute") },
            { key: "d", label: tr("Diferencia (IC 90 %)", "Difference (90% CI)"), numeric: true },
            { key: "p", label: "p TOST", numeric: true },
            { key: "e", label: tr("Equivalente", "Equivalent") },
          ],
          rows: eq.map((r) => ({
            a: aLabel(String(r.attribute)),
            d: fmtCI(r.diff, r.ci90_lo, r.ci90_hi, lang, 3),
            p: fmtP(r.p_tost, lang),
            e: bool(r.equivalent) ? <Badge kind="ok">{tr("Sí", "Yes")}</Badge> : <Badge>{tr("No", "No")}</Badge>,
          })),
        }}
      >
        <Chart option={eqOption} height={forestHeight(eq.length)} label={tr("Equivalencia por atributo", "Equivalence by attribute")} />
      </Figure>

      <SectionTitle title={tr("Enlace notificación–lote", "Report–lot linkage")} />
      <div className="grid two">
        <Figure
          title={tr("Proporción de notificaciones enlazadas por año", "Share of reports linked by year")}
          csvName="p2_linkage_by_year"
          table={{
            columns: [
              { key: "y", label: tr("Año", "Year") },
              { key: "n", label: tr("Notificaciones", "Reports"), numeric: true },
              { key: "l", label: tr("Enlazadas", "Linked"), numeric: true },
            ],
            rows: lby.map((r) => ({ y: String(r.analytic_year), n: fmt(r.n_reports, lang), l: fmt(r.n_linked, lang) })),
          }}
        >
          <Chart option={linkOption} height={barsHeight(6)} label={tr("Enlace por año", "Linkage by year")} />
        </Figure>
        <section className="card">
          <div className="card-head">
            <div>
              <h3>{tr("Sesgo de enlace", "Linkage bias")}</h3>
              <p>{tr("Características de notificaciones enlazadas y no enlazadas", "Characteristics of linked and unlinked reports")}</p>
            </div>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{tr("Grupo", "Group")}</th>
                  <th scope="col" className="num">n</th>
                  <th scope="col" className="num">{tr("Edad mediana (meses)", "Median age (months)")}</th>
                  <th scope="col" className="num">{tr("Mujeres", "Female")}</th>
                  <th scope="col" className="num">{tr("Fiebre ≥39 °C", "Fever ≥39 °C")}</th>
                  <th scope="col" className="num">{tr("Hospitalización", "Hospitalisation")}</th>
                </tr>
              </thead>
              <tbody>
                {bias.map((r) => (
                  <tr key={String(r.linked)}>
                    <td>{bool(r.linked) ? tr("Enlazadas", "Linked") : tr("No enlazadas", "Not linked")}</td>
                    <td className="num">{fmt(r.n, lang)}</td>
                    <td className="num">{fmt(r.age_months_median, lang, 1)}</td>
                    <td className="num">{fmtPct(r.female_pct, lang)}</td>
                    <td className="num">{fmtPct(r.fever39_pct, lang)}</td>
                    <td className="num">{fmtPct(r.hospitalized_pct, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <SectionTitle
        title={tr(`Asociaciones con ${oLabel(outcome).toLowerCase()}`, `Associations with ${oLabel(outcome).toLowerCase()}`)}
        sub={
          Number.isFinite(mde)
            ? tr(`Efecto mínimo detectable: OR ${fmt(mde, lang, 2)} por DE (potencia 80 %)`, `Minimum detectable effect: OR ${fmt(mde, lang, 2)} per SD (80% power)`)
            : undefined
        }
      />
      <Figure
        title={tr("OR por desviación estándar de cada atributo", "OR per standard deviation of each attribute")}
        subtitle={tr(
          "GEE de solo casos, correlación intercambiable dentro del lote, ajustado por edad, sexo, dosis, año y coadministración",
          "Case-only GEE, exchangeable within-lot correlation, adjusted for age, sex, dose, year and co-administration",
        )}
        legend={
          <Legend
            items={[
              { label: tr("Ajustada", "Adjusted"), color: t.s1, shape: "dot" },
              { label: tr("Cruda", "Crude"), color: t.s2, shape: "dot" },
              { label: tr("Bajo el efecto mínimo detectable", "Below the minimum detectable effect"), color: t.band2, shape: "band" },
            ]}
          />
        }
        table={assocTable}
        csvName={`p2_gee_${outcome}`}
      >
        <Chart option={assocOption} height={forestHeight(assoc.cats.length, 2)} label={tr("Gráfico de bosque de asociaciones", "Forest plot of associations")} />
      </Figure>
      <div style={{ height: 16 }} />
      <div className="grid two">
        <Figure
          title={tr(`Sensibilidad: ${aLabel(attribute)}`, `Sensitivity: ${aLabel(attribute)}`)}
          subtitle={tr(`Reacción: ${oLabel(outcome)}`, `Reaction: ${oLabel(outcome)}`)}
        >
          {sensOption && sens ? (
            <Chart option={sensOption} height={forestHeight(sens.length)} label={tr("Análisis de sensibilidad", "Sensitivity analyses")} />
          ) : (
            <p style={{ color: "var(--muted)" }}>
              {tr(
                "Este atributo no forma parte de la familia preespecificada; elija otro atributo en el filtro para ver sus análisis de sensibilidad.",
                "This attribute is not in the prespecified family; choose another attribute in the filter to see its sensitivity analyses.",
              )}
            </p>
          )}
        </Figure>
        <section className="card">
          <div className="card-head">
            <div>
              <h3>{tr("Valor predictivo incremental", "Incremental predictive value")}</h3>
              <p>{tr("AUROC con validación cruzada agrupada por lote y prueba de permutación entre lotes", "AUROC with lot-grouped cross-validation and between-lot permutation test")}</p>
            </div>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{tr("Reacción", "Reaction")}</th>
                  <th scope="col" className="num">{tr("Base", "Base")}</th>
                  <th scope="col" className="num">{tr("+ atributos", "+ attributes")}</th>
                  <th scope="col" className="num">Δ AUROC</th>
                  <th scope="col" className="num">p</th>
                </tr>
              </thead>
              <tbody>
                {inc.map((r) => (
                  <tr key={String(r.outcome)}>
                    <td>{oLabel(String(r.outcome))}</td>
                    <td className="num">{fmt(r.auc_base, lang, 3)}</td>
                    <td className="num">{fmt(r.auc_with_qc, lang, 3)}</td>
                    <td className="num">{fmt(r.delta_auc, lang, 3)}</td>
                    <td className="num">{fmtP(r.perm_p, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
