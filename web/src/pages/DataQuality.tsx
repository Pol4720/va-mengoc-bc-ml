// Data quality of the AEFI files and public epidemiological context.

import { useMemo } from "react";
import { bandLine, heatmap, lines, observedFitted } from "../charts/builders";
import { Chart } from "../components/Chart";
import { Figure, Legend, SectionTitle, StatTile } from "../components/ui";
import { num, object, table } from "../data/bundle";
import { fmt, fmtCI, fmtPct } from "../data/format";
import { completenessFloor, dqSummary } from "../data/summary";
import { useLang } from "../i18n";
import { useBundle } from "../state";
import { useTokens } from "../theme";

const FIELD_LABELS: Record<string, [string, string]> = {
  age_months: ["Edad", "Age"],
  doses: ["Dosis", "Dose"],
  lots_exact: ["Lote (exacto)", "Lot (exact)"],
  manufacturers: ["Fabricante", "Manufacturer"],
  notification_date: ["Fecha de notificación", "Notification date"],
  place: ["Lugar de vacunación", "Place of vaccination"],
  province: ["Provincia", "Province"],
  sex: ["Sexo", "Sex"],
  vaccines: ["Vacunas", "Vaccines"],
};

interface Its {
  intervention_year?: number;
  level_change_rr?: { rr: number; lo: number; hi: number };
  slope_change_rr?: { rr: number; lo: number; hi: number };
}

export function DataQuality() {
  const { bundle } = useBundle();
  const { lang, tr } = useLang();
  const t = useTokens();
  const s = useMemo(() => dqSummary(bundle), [bundle]);
  const fieldLabel = (f: string) => {
    const p = FIELD_LABELS[f];
    return p ? (lang === "es" ? p[0] : p[1]) : f;
  };

  const comp = table(bundle, "dq_completeness");
  const compOption = useMemo(() => {
    const years = [...new Set(comp.map((r) => num(r.file_year)))].sort((a, b) => a - b);
    const fields = [...new Set(comp.map((r) => String(r.field)))];
    return heatmap(t, lang, {
      x: years.map(String),
      y: fields.map(fieldLabel),
      cells: comp.map((r) => [years.indexOf(num(r.file_year)), fields.indexOf(String(r.field)), num(r.pct_present)]),
      min: completenessFloor(comp.map((r) => num(r.pct_present))),
      max: 100,
      digits: 1,
      valueLabel: tr("Completitud (%)", "Completeness (%)"),
      showLabels: true,
    });
  }, [comp, t, lang, tr]); // eslint-disable-line react-hooks/exhaustive-deps

  const plaus = table(bundle, "dq_plausibility");
  const checks = useMemo(() => {
    const by = new Map<string, { label: string; category: string; flagged: number; records: number }>();
    for (const r of plaus) {
      const k = String(r.check);
      const cur = by.get(k) ?? {
        label: String(lang === "es" ? r.label_es : r.label_en),
        category: String(r.category),
        flagged: 0,
        records: 0,
      };
      const f = num(r.n_flagged);
      cur.flagged += Number.isFinite(f) ? f : 0;
      cur.records += num(r.n_records) || 0;
      by.set(k, cur);
    }
    return [...by.values()].sort((a, b) => b.flagged - a.flagged);
  }, [plaus, lang]);

  const conf = table(bundle, "dq_conformance");
  const confByField = useMemo(() => {
    const by = new Map<string, { n: number; ok: number; rec: number; miss: number }>();
    for (const r of conf) {
      const k = String(r.field);
      const cur = by.get(k) ?? { n: 0, ok: 0, rec: 0, miss: 0 };
      const add = (v: unknown) => {
        const x = num(v as never);
        return Number.isFinite(x) ? x : 0;
      };
      cur.n += add(r.n);
      cur.ok += add(r.n_ok);
      cur.rec += add(r.n_recovered);
      cur.miss += add(r.n_missing);
      by.set(k, cur);
    }
    return [...by.entries()].map(([field, v]) => ({ field, ...v }));
  }, [conf]);

  const delay = table(bundle, "p1_notification_delay");
  const delayOption = useMemo(
    () =>
      bandLine(t, lang, {
        x: delay.map((r) => String(r.analytic_year)),
        y: delay.map((r) => num(r["50%"])),
        lo: delay.map((r) => num(r["25%"])),
        hi: delay.map((r) => num(r["75%"])),
        name: tr("Mediana (días)", "Median (days)"),
        bandLabel: tr("Rango intercuartílico", "Interquartile range"),
        digits: 0,
        yMin: 0,
      }),
    [delay, t, lang, tr],
  );

  const inc = table(bundle, "context_incidence_fitted");
  const its = object<Its>(bundle, "context_incidence_its");
  const incOption = useMemo(
    () =>
      observedFitted(t, lang, {
        x: inc.map((r) => String(r.year)),
        observed: inc.map((r) => num(r.cases)),
        fitted: inc.map((r) => num(r.fitted)),
        observedName: tr("Casos notificados", "Reported cases"),
        fittedName: tr("Ajuste segmentado (binomial negativa)", "Segmented fit (negative binomial)"),
        xRefs: its?.intervention_year
          ? [{ value: inc.findIndex((r) => num(r.year) === its.intervention_year), label: tr(`vacunación masiva ${its.intervention_year}`, `mass vaccination ${its.intervention_year}`) }]
          : undefined,
      }),
    [inc, its, t, lang, tr],
  );
  const cov = useMemo(() => table(bundle, "context_coverage").filter((r) => Number.isFinite(num(r.coverage_pct))), [bundle]);
  const covOption = useMemo(() => {
    const v = cov.map((r) => num(r.coverage_pct));
    const lo = v.length ? Math.max(0, Math.floor(Math.min(...v) / 10) * 10 - 10) : 0;
    return lines(t, lang, {
      x: cov.map((r) => String(r.year)),
      series: [{ name: tr("Cobertura (%)", "Coverage (%)"), color: t.s1, values: v, symbol: true }],
      digits: 1,
      yMin: lo,
      yMax: 100,
    });
  }, [cov, t, lang, tr]);
  const notes = object<{ incidence?: string[]; coverage?: string[] }>(bundle, "provenance_notes");

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{tr("Transparencia", "Transparency")}</div>
        <h1>{tr("Calidad de datos y contexto", "Data quality and context")}</h1>
        <p className="lede">
          {tr(
            "Antes de cualquier análisis, el pipeline mide qué falta, qué no cumple el formato y qué es implausible. Nada se borra en silencio: cada decisión queda contada.",
            "Before any analysis, the pipeline measures what is missing, what does not conform and what is implausible. Nothing is silently dropped: every decision is counted.",
          )}
        </p>
      </header>

      <div className="kpis">
        <StatTile label={tr("Registros evaluados", "Records assessed")} value={fmt(s.nRecords, lang)} sub={tr(`${s.nFiles} ficheros anuales`, `${s.nFiles} annual files`)} />
        <StatTile label={tr("Completitud media", "Mean completeness")} value={fmtPct(s.meanCompleteness, lang)} sub={tr("campos clave por año", "key fields by year")} />
        <StatTile label={tr("Comprobaciones de plausibilidad", "Plausibility checks")} value={fmt(s.nChecks, lang)} sub={tr(`${fmt(s.flagged, lang)} marcas publicables`, `${fmt(s.flagged, lang)} releasable flags`)} />
      </div>

      <SectionTitle title={tr("Completitud y conformidad", "Completeness and conformance")} />
      <div className="grid two">
        <Figure
          title={tr("Completitud por campo y año", "Completeness by field and year")}
          subtitle={tr("Porcentaje de registros con el campo presente", "Percentage of records with the field present")}
          csvName="dq_completeness"
          table={{
            columns: [
              { key: "y", label: tr("Año", "Year") },
              { key: "f", label: tr("Campo", "Field") },
              { key: "p", label: "%", numeric: true },
            ],
            rows: comp.map((r) => ({ y: String(r.file_year), f: fieldLabel(String(r.field)), p: fmtPct(r.pct_present, lang) })),
          }}
        >
          <Chart option={compOption} height={380} label={tr("Mapa de calor de completitud", "Completeness heat map")} />
        </Figure>
        <section className="card">
          <div className="card-head">
            <div>
              <h3>{tr("Conformidad de formato", "Format conformance")}</h3>
              <p>{tr("Valores válidos, recuperados por las reglas de normalización y ausentes (todos los ficheros)", "Valid values, recovered by the normalisation rules and missing (all files)")}</p>
            </div>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{tr("Campo", "Field")}</th>
                  <th scope="col" className="num">n</th>
                  <th scope="col" className="num">{tr("Válidos", "Valid")}</th>
                  <th scope="col" className="num">{tr("Recuperados", "Recovered")}</th>
                  <th scope="col" className="num">{tr("Ausentes", "Missing")}</th>
                </tr>
              </thead>
              <tbody>
                {confByField.map((r) => (
                  <tr key={r.field}>
                    <td>{r.field.replace(/_/g, " ")}</td>
                    <td className="num">{fmt(r.n, lang)}</td>
                    <td className="num">{fmtPct(r.n ? (r.ok / r.n) * 100 : NaN, lang)}</td>
                    <td className="num">{fmt(r.rec, lang)}</td>
                    <td className="num">{fmt(r.miss, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="card-note">
            {tr("Los recuentos suprimidos (<5) se cuentan como cero en estas sumas.", "Suppressed counts (<5) are counted as zero in these sums.")}
          </p>
        </section>
      </div>

      <SectionTitle title={tr("Plausibilidad", "Plausibility")} />
      <div className="grid two">
        <section className="card">
          <div className="card-head">
            <div>
              <h3>{tr("Comprobaciones de plausibilidad", "Plausibility checks")}</h3>
              <p>{tr("Registros marcados en todos los años; se informan, no se eliminan", "Records flagged across all years; reported, not removed")}</p>
            </div>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{tr("Comprobación", "Check")}</th>
                  <th scope="col">{tr("Tipo", "Type")}</th>
                  <th scope="col" className="num">{tr("Marcados", "Flagged")}</th>
                  <th scope="col" className="num">%</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c) => (
                  <tr key={c.label}>
                    <td style={{ whiteSpace: "normal", minWidth: 220 }}>{c.label}</td>
                    <td>{c.category.split("/").pop()}</td>
                    <td className="num">{fmt(c.flagged, lang)}</td>
                    <td className="num">{fmtPct(c.records ? (c.flagged / c.records) * 100 : NaN, lang, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <Figure
          title={tr("Demora de notificación", "Notification delay")}
          subtitle={tr("Días entre vacunación y notificación por año", "Days between vaccination and notification by year")}
          legend={
            <Legend
              items={[
                { label: tr("Mediana", "Median"), color: t.s1 },
                { label: tr("Rango intercuartílico", "Interquartile range"), color: t.band2, shape: "band" },
              ]}
            />
          }
          csvName="p1_notification_delay"
          table={{
            columns: [
              { key: "y", label: tr("Año", "Year") },
              { key: "n", label: "n", numeric: true },
              { key: "m", label: tr("Mediana (RIC)", "Median (IQR)"), numeric: true },
              { key: "p90", label: "P90", numeric: true },
            ],
            rows: delay.map((r) => ({
              y: String(r.analytic_year),
              n: fmt(r.count, lang),
              m: fmtCI(r["50%"], r["25%"], r["75%"], lang, 0),
              p90: fmt(r["90%"], lang),
            })),
          }}
        >
          <Chart option={delayOption} height={300} label={tr("Demora de notificación por año", "Notification delay by year")} />
        </Figure>
      </div>

      <SectionTitle title={tr("Contexto epidemiológico", "Epidemiological context")} sub={tr("Series públicas nacionales", "Public national series")} />
      <div className="grid two">
        <Figure
          title={tr("Enfermedad meningocócica en Cuba", "Meningococcal disease in Cuba")}
          subtitle={
            its?.level_change_rr
              ? tr(
                  `Cambio de nivel tras la vacunación: RR ${fmtCI(its.level_change_rr.rr, its.level_change_rr.lo, its.level_change_rr.hi, lang, 3)}`,
                  `Level change after vaccination: RR ${fmtCI(its.level_change_rr.rr, its.level_change_rr.lo, its.level_change_rr.hi, lang, 3)}`,
                )
              : undefined
          }
          legend={
            <Legend
              items={[
                { label: tr("Casos notificados", "Reported cases"), color: t.s1, shape: "dot" },
                { label: tr("Ajuste segmentado", "Segmented fit"), color: t.s2 },
              ]}
            />
          }
          note={notes?.incidence?.[0]}
          csvName="context_incidence"
          table={{
            columns: [
              { key: "y", label: tr("Año", "Year") },
              { key: "c", label: tr("Casos", "Cases"), numeric: true },
              { key: "f", label: tr("Ajuste", "Fit"), numeric: true },
            ],
            rows: inc.map((r) => ({ y: String(r.year), c: fmt(r.cases, lang), f: fmt(r.fitted, lang, 1) })),
          }}
        >
          <Chart option={incOption} height={300} label={tr("Serie de incidencia con ajuste", "Incidence series with fit")} />
        </Figure>
        <Figure
          title={tr("Cobertura de vacunación con VA-MENGOC-BC", "VA-MENGOC-BC vaccination coverage")}
          note={notes?.coverage?.[0]}
          csvName="context_coverage"
          table={{
            columns: [
              { key: "y", label: tr("Año", "Year") },
              { key: "d", label: tr("Dosis", "Doses"), numeric: true },
              { key: "c", label: tr("Cobertura", "Coverage"), numeric: true },
            ],
            rows: cov.map((r) => ({ y: String(r.year), d: fmt(r.doses_administered, lang), c: fmtPct(r.coverage_pct, lang) })),
          }}
        >
          <Chart option={covOption} height={300} label={tr("Cobertura por año", "Coverage by year")} />
        </Figure>
      </div>
    </>
  );
}
