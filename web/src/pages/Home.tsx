// Guided story: what the pipeline does, step by step, with the headline results of this bundle.

import { useEffect, useMemo, useState } from "react";
import { Reveal } from "../components/Reveal";
import { SectionTitle, StatTile } from "../components/ui";
import { fmt, fmtPct } from "../data/format";
import { dqSummary, p1Summary, p2Summary } from "../data/summary";
import { useLang } from "../i18n";
import { useBundle } from "../state";
import { prefersReducedMotion } from "../theme";
import { PIPELINE_STEPS } from "../content/pipeline";

const STEP_MS = 5200;

export function Home() {
  const { bundle } = useBundle();
  const { lang, tr } = useLang();
  const p1 = useMemo(() => p1Summary(bundle), [bundle]);
  const p2 = useMemo(() => p2Summary(bundle), [bundle]);
  const dq = useMemo(() => dqSummary(bundle), [bundle]);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(() => !prefersReducedMotion());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!playing) return undefined;
    const tick = 100;
    const id = window.setInterval(() => {
      setElapsed((e) => {
        if (e + tick >= STEP_MS) {
          setStep((s) => (s + 1) % PIPELINE_STEPS.length);
          return 0;
        }
        return e + tick;
      });
    }, tick);
    return () => window.clearInterval(id);
  }, [playing]);

  const go = (i: number) => {
    setStep((i + PIPELINE_STEPS.length) % PIPELINE_STEPS.length);
    setElapsed(0);
  };
  const cur = PIPELINE_STEPS[step] ?? PIPELINE_STEPS[0]!;
  const L = (p: [string, string]) => (lang === "es" ? p[0] : p[1]);
  const rate = p1.trend.pooled_rate_per_100k;

  return (
    <>
      <section className="hero">
        <div>
          <div className="eyebrow">{tr("Instituto Finlay de Vacunas · DICEI", "Finlay Vaccine Institute · DICEI")}</div>
          <h1>
            {tr("Del registro a la evidencia: ", "From records to evidence: ")}
            <span>
              {tr("seguridad y calidad de ", "safety and quality of ")}
              <span className="nowrap">VA-MENGOC-BC</span>
            </span>
          </h1>
          <p className="lede">
            {tr(
              "Un pipeline reproducible convierte las notificaciones de eventos adversos y los registros de liberación de lotes en dos estudios listos para publicar. Explore cada paso, los resultados y el laboratorio para repetir el experimento con otros parámetros.",
              "A reproducible pipeline turns adverse-event reports and lot release records into two publication-ready studies. Explore each step, the results and the lab to rerun the experiment with other parameters.",
            )}
          </p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <a className="btn primary" href="#/pv">
              {tr("Ver farmacovigilancia", "See pharmacovigilance")}
            </a>
            <a className="btn" href="#/lots">
              {tr("Ver calidad de lotes", "See lot quality")}
            </a>
            <a className="btn" href="#/slides">
              {tr("Presentaciones", "Slide decks")}
            </a>
          </div>
        </div>
        <div className="hero-card">
          <div className="stat-label" style={{ color: "var(--ink-2)", fontWeight: 550, fontSize: "0.9rem" }}>
            {tr("Notificaciones de ESAVI con VA-MENGOC-BC", "AEFI reports with VA-MENGOC-BC")}
          </div>
          <div className="hero-figure">{fmt(p1.targetReports, lang)}</div>
          <p style={{ color: "var(--muted)", fontSize: "0.88rem", margin: "6px 0 14px" }}>
            {tr(
              `de ${fmt(p1.allReports, lang)} notificaciones, ${p1.firstYear}–${p1.lastYear}`,
              `of ${fmt(p1.allReports, lang)} reports, ${p1.firstYear}–${p1.lastYear}`,
            )}
          </p>
          <div className="kpis" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            <StatTile
              label={tr("Tasa por 100 000 dosis", "Rate per 100,000 doses")}
              value={rate !== undefined ? fmt(rate, lang, 1) : "—"}
              sub={tr("conjunta, todos los años", "pooled, all years")}
            />
            <StatTile
              label={tr("Señales preespecificadas", "Prespecified signals")}
              value={fmt(p1.flagged.length, lang)}
              sub={tr(`${p1.robust.length} robustas en todos los diseños`, `${p1.robust.length} robust across designs`)}
            />
            <StatTile
              label={tr("Lotes analizados", "Lots analysed")}
              value={fmt(p2.nLotsAnalysed, lang)}
              sub={tr(`enlace ${fmtPct(p2.linkRate * 100, lang)}`, `linkage ${fmtPct(p2.linkRate * 100, lang)}`)}
            />
            <StatTile
              label={tr("Asociaciones (FDR < 5 %)", "Associations (FDR < 5%)")}
              value={`${fmt(p2.significant.length, lang)} / ${fmt(p2.nAssociations, lang)}`}
              sub={tr("atributo de lote × reacción", "lot attribute × reaction")}
            />
          </div>
        </div>
      </section>

      <Reveal>
        <section className="card" aria-labelledby="pipe-title">
          <div className="card-head">
            <div>
              <h3 id="pipe-title">{tr("Cómo se procesan los datos", "How the data are processed")}</h3>
              <p>
                {tr(
                  "Ocho pasos automáticos; pulse cualquiera para ver qué hace y qué garantiza.",
                  "Eight automated steps; select any of them to see what it does and what it guarantees.",
                )}
              </p>
            </div>
          </div>
          <div className="pipeline" role="tablist" aria-label={tr("Pasos del pipeline", "Pipeline steps")}>
            {PIPELINE_STEPS.map((s, i) => (
              <button
                key={s.key}
                type="button"
                role="tab"
                id={`pipe-tab-${s.key}`}
                aria-selected={i === step}
                aria-controls="pipe-panel"
                className={`pipe-step${i === step ? " active" : i < step ? " done" : ""}`}
                onClick={() => {
                  go(i);
                  setPlaying(false);
                }}
              >
                <span className="pipe-node">{i + 1}</span>
                <span className="pipe-label">{L(s.title)}</span>
              </button>
            ))}
          </div>
          <div
            key={cur.key}
            className="pipe-detail"
            id="pipe-panel"
            role="tabpanel"
            aria-labelledby={`pipe-tab-${cur.key}`}
            aria-live="polite"
          >
            <div>
              <h3 style={{ fontSize: "1.25rem" }}>
                {step + 1}. {L(cur.title)}
              </h3>
              <p style={{ color: "var(--ink-2)" }}>{L(cur.what)}</p>
              <ul>
                {cur.bullets.map((b) => (
                  <li key={b[0]}>{L(b)}</li>
                ))}
              </ul>
            </div>
            <dl>
              <dt>{tr("Garantía", "Guarantee")}</dt>
              <dd>
                <strong>{L(cur.guarantee)}</strong>
              </dd>
              <dt>{tr("Código", "Code")}</dt>
              <dd>
                <code>{cur.module}</code>
              </dd>
              <dt>{tr("Salida", "Output")}</dt>
              <dd>{L(cur.output)}</dd>
            </dl>
          </div>
          <div className="pipe-controls">
            <button type="button" className="btn small" onClick={() => go(step - 1)} aria-label={tr("Paso anterior", "Previous step")}>
              ←
            </button>
            <button type="button" className="btn small" onClick={() => setPlaying((p) => !p)} aria-pressed={playing}>
              {playing ? tr("Pausar", "Pause") : tr("Reproducir", "Play")}
            </button>
            <button type="button" className="btn small" onClick={() => go(step + 1)} aria-label={tr("Paso siguiente", "Next step")}>
              →
            </button>
            <div className="progress" aria-hidden="true">
              <div style={{ width: `${playing ? (elapsed / STEP_MS) * 100 : 100}%` }} />
            </div>
          </div>
        </section>
      </Reveal>

      <SectionTitle
        title={tr("Explorar los resultados", "Explore the results")}
        sub={tr("Cada cifra procede del release con control de divulgación.", "Every figure comes from the disclosure-controlled release.")}
      />
      <Reveal>
        <div className="tiles-link">
          <a className="tile-link" href="#/pv">
            <h3>{tr("Artículo 1 · Farmacovigilancia", "Paper 1 · Pharmacovigilance")}</h3>
            <p>
              {tr(
                `Tasas de notificación, ${p1.designs.length} diseños de desproporcionalidad con umbrales ajustables, fenotipos latentes y modelo de hospitalización.`,
                `Reporting rates, ${p1.designs.length} disproportionality designs with adjustable thresholds, latent phenotypes and the hospitalisation model.`,
              )}
            </p>
          </a>
          <a className="tile-link" href="#/lots">
            <h3>{tr("Artículo 2 · Calidad de lotes", "Paper 2 · Lot quality")}</h3>
            <p>
              {tr(
                "Capacidad de proceso, gráficos de control por atributo, MSPC y asociación entre atributos de liberación y reactogenicidad.",
                "Process capability, per-attribute control charts, MSPC and the association between release attributes and reactogenicity.",
              )}
            </p>
          </a>
          <a className="tile-link" href="#/data">
            <h3>{tr("Calidad de datos y contexto", "Data quality and context")}</h3>
            <p>
              {tr(
                `${fmt(dq.nChecks, lang)} comprobaciones sobre ${fmt(dq.nRecords, lang)} registros, completitud por campo y serie histórica de enfermedad meningocócica.`,
                `${fmt(dq.nChecks, lang)} checks on ${fmt(dq.nRecords, lang)} records, completeness by field and the historical meningococcal disease series.`,
              )}
            </p>
          </a>
          <a className="tile-link" href="#/lab">
            <h3>{tr("Laboratorio", "Lab")}</h3>
            <p>
              {tr(
                "Conecte la aplicación al pipeline local, cambie parámetros y genere un nuevo conjunto de resultados verificado.",
                "Connect the app to the local pipeline, change parameters and generate a new verified set of results.",
              )}
            </p>
          </a>
        </div>
      </Reveal>

      <SectionTitle title={tr("Reproducir en su equipo", "Reproduce on your computer")} />
      <Reveal>
        <div className="grid two">
          <div className="card">
            <h3>{tr("Con datos sintéticos (cualquier persona)", "With synthetic data (anyone)")}</h3>
            <pre className="code">
              <code>{`uv sync --all-extras
uv run vamengoc demo          # ${tr("genera datos y release sintéticos", "builds synthetic data and release")}
uv run vamengoc serve         # ${tr("API local del laboratorio", "local lab API")}
cd web && npm ci && npm run dev`}</code>
            </pre>
          </div>
          <div className="card">
            <h3>{tr("Con los datos reales (custodio autorizado)", "With the real data (authorised custodian)")}</h3>
            <pre className="code">
              <code>{`# ${tr("ficheros en data/raw/ (ignorados por git)", "files in data/raw/ (ignored by git)")}
uv run vamengoc keygen        # ${tr("clave HMAC fuera del repositorio", "HMAC key outside the repository")}
uv run vamengoc run           # ${tr("pipeline completo + release público", "full pipeline + public release")}
uv run vamengoc release verify`}</code>
            </pre>
          </div>
        </div>
      </Reveal>
    </>
  );
}
