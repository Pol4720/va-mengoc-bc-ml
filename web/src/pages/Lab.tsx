// Analysis lab: connects to the local API, lets the user customise whitelisted parameters, runs the
// pipeline locally and loads the verified, disclosure-controlled results into the app.

import { useEffect, useMemo, useRef, useState } from "react";
import { SectionTitle } from "../components/ui";
import { buildOverrides, checkValue, DEFAULT_API, LabClient, type Health, type Job, type JobStep, type Tunable } from "../data/lab";
import { useLang } from "../i18n";
import { useBundle } from "../state";

const STEP_LABELS: Record<string, [string, string]> = {
  generate_synthetic: ["Generar datos sintéticos", "Generate synthetic data"],
  ingest_aefi_file: ["Lectura de ficheros anuales de ESAVI", "Read annual AEFI files"],
  ingest_aefi: ["Notificaciones ingeridas", "Reports ingested"],
  lots_sheet_skip_row: ["Registro de lotes: filas omitidas", "Lot register: rows skipped"],
  ingest_lots_sheet: ["Registro de lotes", "Lot register"],
  ingest_incidence: ["Serie de incidencia", "Incidence series"],
  ingest_coverage: ["Serie de cobertura", "Coverage series"],
  deduplicate: ["Eliminación de duplicados", "Deduplication"],
  derive_analytic_variables: ["Variables analíticas", "Analytical variables"],
  link_reports_to_lots: ["Enlace con lotes", "Lot linkage"],
  analyze_paper1: ["Análisis del artículo 1", "Paper 1 analysis"],
  analyze_paper2: ["Análisis del artículo 2", "Paper 2 analysis"],
  build_release: ["Release con control de divulgación", "Disclosure-controlled release"],
};

const OPTION_LABELS: Record<string, [string, string]> = {
  vaccination_date: ["Fecha de vacunación", "Vaccination date"],
  notification_date: ["Fecha de notificación", "Notification date"],
  file_year: ["Año del fichero", "File year"],
  ic: ["IC025 > 0 (BCPNN)", "IC025 > 0 (BCPNN)"],
  ror: ["Límite inferior del ROR > 1", "ROR lower bound > 1"],
  prr: ["PRR ≥ 2 y χ² ≥ 4", "PRR ≥ 2 and χ² ≥ 4"],
  ebgm: ["EB05 ≥ umbral (MGPS)", "EB05 ≥ threshold (MGPS)"],
  consensus2: ["Al menos dos métodos", "At least two methods"],
  exchangeable: ["Intercambiable", "Exchangeable"],
  independence: ["Independencia", "Independence"],
};

export interface StepGroup {
  step: string;
  count: number;
  rows: number | null;
}

/** Collapse consecutive repetitions of a step (one per annual file, one per skipped row…). */
export function groupSteps(steps: JobStep[]): StepGroup[] {
  const out: StepGroup[] = [];
  for (const s of steps) {
    if (s.step === "traceback") continue;
    const n = typeof s.rows_out === "number" ? s.rows_out : typeof s.rows_in === "number" ? s.rows_in : null;
    const last = out[out.length - 1];
    if (last && last.step === s.step) {
      last.count += 1;
      last.rows = n === null ? last.rows : (last.rows ?? 0) + n;
    } else {
      out.push({ step: s.step, count: 1, rows: n });
    }
  }
  return out;
}

const POLL_MS = 1500;

export function Lab() {
  const { lang, tr } = useLang();
  const { setLabBundle, origin } = useBundle();
  const [api, setApi] = useState(DEFAULT_API);
  const [token, setToken] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [tunables, setTunables] = useState<Tunable[]>([]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [source, setSource] = useState<"synthetic" | "raw">("synthetic");
  const [scale, setScale] = useState(0.1);
  const [seed, setSeed] = useState(20260930);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const timer = useRef<number | null>(null);

  const client = useMemo(() => new LabClient(api, token), [api, token]);
  const defaults = useMemo(() => Object.fromEntries(tunables.map((t) => [t.path, t.value])), [tunables]);
  const invalid = tunables.filter((t) => checkValue(t, values[t.path]) !== null);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  async function connect() {
    setError(null);
    setBusy(true);
    try {
      const h = await client.health();
      setHealth(h);
      const t = await client.tunables();
      setTunables(t.tunables);
      setValues(Object.fromEntries(t.tunables.map((x) => [x.path, x.value])));
    } catch (e) {
      setHealth(null);
      setTunables([]);
      setError(
        tr(
          `No se pudo conectar (${(e as Error).message}). ¿Está en marcha «uv run vamengoc serve» y el token es correcto?`,
          `Could not connect (${(e as Error).message}). Is "uv run vamengoc serve" running and the token correct?`,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  function poll(id: string) {
    timer.current = window.setTimeout(async () => {
      try {
        const j = await client.job(id);
        setJob(j);
        if (j.status === "queued" || j.status === "running") poll(id);
      } catch (e) {
        setError((e as Error).message);
      }
    }, POLL_MS);
  }

  async function run() {
    setError(null);
    try {
      const j = await client.submit({
        source,
        overrides: buildOverrides(values, defaults),
        synthetic_scale: scale,
        synthetic_seed: seed,
        regenerate_synthetic: true,
      });
      setJob(j);
      poll(j.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function load() {
    if (!job) return;
    try {
      setLabBundle(await client.bundle(job.id));
      window.location.hash = "#/pv";
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const set = (path: string, v: unknown) => setValues((cur) => ({ ...cur, [path]: v }));
  const running = job?.status === "queued" || job?.status === "running";

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{tr("Personalizar el experimento", "Customise the experiment")}</div>
        <h1>{tr("Laboratorio de análisis", "Analysis lab")}</h1>
        <p className="lede">
          {tr(
            "La aplicación publicada nunca ve datos individuales. Para cambiar parámetros, el pipeline se ejecuta en su propio equipo y devuelve solo un release verificado con control de divulgación.",
            "The published app never sees individual data. To change parameters, the pipeline runs on your own computer and returns only a verified, disclosure-controlled release.",
          )}
        </p>
      </header>

      {origin !== "release" ? (
        <div className="notice">
          <div className="grow">
            {tr(`Mostrando resultados del laboratorio (trabajo ${origin}).`, `Showing lab results (job ${origin}).`)}
          </div>
          <button type="button" className="btn small" onClick={() => setLabBundle(null)}>
            {tr("Volver al release publicado", "Back to the published release")}
          </button>
        </div>
      ) : null}

      <div className="lab-grid">
        <section className="card">
          <h3>{tr("1. Iniciar la API local", "1. Start the local API")}</h3>
          <pre className="code">
            <code>{`uv sync --extra app
uv run vamengoc serve   # http://127.0.0.1:8765`}</code>
          </pre>
          <p className="card-note">
            {tr(
              "La API solo escucha en 127.0.0.1, exige el token de sesión que imprime al arrancar y solo acepta los parámetros de la lista blanca.",
              "The API listens on 127.0.0.1 only, requires the session token it prints at start-up and accepts only whitelisted parameters.",
            )}
          </p>
          <div className="form-grid" style={{ marginTop: 12 }}>
            <label className="field">
              {tr("Dirección de la API", "API address")}
              <input type="url" value={api} onChange={(e) => setApi(e.target.value)} spellCheck={false} />
            </label>
            <label className="field">
              {tr("Token de sesión", "Session token")}
              <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" spellCheck={false} />
            </label>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
            <button type="button" className="btn primary" onClick={connect} disabled={busy || !token}>
              {busy ? <span className="spinner" aria-hidden="true" /> : null}
              {tr("Conectar", "Connect")}
            </button>
            {health ? (
              <span className="status-pill">
                <span className="dot" style={{ background: "var(--good)" }} aria-hidden="true" />
                {tr(`Conectado · vamengoc ${health.version}`, `Connected · vamengoc ${health.version}`)}
              </span>
            ) : null}
          </div>
          {error ? (
            <p role="alert" style={{ color: "var(--critical)", marginTop: 10, fontSize: "0.9rem" }}>
              ⚠ {error}
            </p>
          ) : null}
        </section>

        <section className="card" aria-live="polite">
          <h3>{tr("3. Ejecución", "3. Run")}</h3>
          {!job ? (
            <p style={{ color: "var(--muted)" }}>
              {tr("Aún no se ha lanzado ningún experimento.", "No experiment has been launched yet.")}
            </p>
          ) : (
            <>
              <p className="status-pill">
                {running ? <span className="spinner" aria-hidden="true" /> : (
                  <span
                    className="dot"
                    aria-hidden="true"
                    style={{ background: job.status === "done" ? "var(--good)" : "var(--critical)" }}
                  />
                )}
                {job.status === "done"
                  ? tr("Terminado y verificado", "Finished and verified")
                  : job.status === "failed"
                    ? tr("Fallido", "Failed")
                    : tr("En curso…", "Running…")}
                <code style={{ fontWeight: 400 }}>{job.id}</code>
              </p>
              <ol className="timeline">
                {groupSteps(job.steps).map((g, i) => {
                  const lbl = STEP_LABELS[g.step];
                  return (
                    <li key={`${g.step}-${i}`}>
                      <span aria-hidden="true">✓</span>
                      <span>
                        {lbl ? (lang === "es" ? lbl[0] : lbl[1]) : g.step}
                        {g.count > 1 ? <span style={{ color: "var(--muted)" }}> ×{g.count}</span> : null}
                        {g.rows !== null ? (
                          <span style={{ color: "var(--muted)" }}> · {g.rows.toLocaleString(lang === "es" ? "es-ES" : "en-GB")}</span>
                        ) : null}
                      </span>
                    </li>
                  );
                })}
              </ol>
              {job.error ? (
                <p role="alert" style={{ color: "var(--critical)", fontSize: "0.9rem" }}>
                  {job.error}
                </p>
              ) : null}
              {job.verification ? (
                <p className="card-note">
                  {tr(
                    `Verificación del release: ${job.verification.ok ? "correcta" : "fallida"} (${job.verification.files} ficheros).`,
                    `Release verification: ${job.verification.ok ? "passed" : "failed"} (${job.verification.files} files).`,
                  )}
                </p>
              ) : null}
              {job.status === "done" && job.has_bundle ? (
                <button type="button" className="btn primary" onClick={load} style={{ marginTop: 8 }}>
                  {tr("Cargar estos resultados en la aplicación", "Load these results into the app")}
                </button>
              ) : null}
            </>
          )}
        </section>
      </div>

      <SectionTitle title={tr("2. Parámetros del experimento", "2. Experiment parameters")} />
      <section className="card">
        {tunables.length === 0 ? (
          <p style={{ color: "var(--muted)", margin: 0 }}>
            {tr("Conéctese a la API para cargar los parámetros ajustables.", "Connect to the API to load the tunable parameters.")}
          </p>
        ) : (
          <>
            <div className="form-grid">
              <label className="field">
                {tr("Fuente de datos", "Data source")}
                <select value={source} onChange={(e) => setSource(e.target.value as "synthetic" | "raw")}>
                  <option value="synthetic">{tr("Sintéticos (generados ahora)", "Synthetic (generated now)")}</option>
                  <option value="raw" disabled={!health?.raw_data_present}>
                    {tr("Reales (data/raw, solo custodio)", "Real (data/raw, custodian only)")}
                  </option>
                </select>
              </label>
              {source === "synthetic" ? (
                <>
                  <label className="field">
                    {tr(`Escala sintética: ${scale}`, `Synthetic scale: ${scale}`)}
                    <input type="range" min={0.05} max={1} step={0.05} value={scale} onChange={(e) => setScale(Number(e.target.value))} />
                  </label>
                  <label className="field">
                    {tr("Semilla de los datos sintéticos", "Synthetic data seed")}
                    <input type="number" value={seed} onChange={(e) => setSeed(Math.trunc(Number(e.target.value)))} />
                  </label>
                </>
              ) : null}
              {tunables.map((t) => (
                <TunableField key={t.path} t={t} value={values[t.path]} onChange={(v) => set(t.path, v)} invalid={checkValue(t, values[t.path]) !== null} />
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
              <button type="button" className="btn primary" onClick={run} disabled={running || invalid.length > 0}>
                {tr("Ejecutar el pipeline", "Run the pipeline")}
              </button>
              <button type="button" className="btn" onClick={() => setValues(defaults)} disabled={running}>
                {tr("Restablecer valores", "Reset values")}
              </button>
              {invalid.length ? (
                <span style={{ color: "var(--critical)", fontSize: "0.88rem", alignSelf: "center" }}>
                  {tr(`${invalid.length} valor(es) fuera de rango`, `${invalid.length} value(s) out of range`)}
                </span>
              ) : null}
            </div>
          </>
        )}
      </section>
    </>
  );
}

function TunableField({ t, value, onChange, invalid }: { t: Tunable; value: unknown; onChange: (v: unknown) => void; invalid: boolean }) {
  const { lang } = useLang();
  const label = lang === "es" ? t.es : t.en;
  const bounds = t.min !== undefined && t.max !== undefined ? ` [${t.min}–${t.max}]` : "";
  const style = invalid ? { borderColor: "var(--critical)" } : undefined;
  if (t.type === "bool") {
    return (
      <label className="check" style={{ alignSelf: "end" }}>
        <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  }
  if (t.type === "enum") {
    return (
      <label className="field">
        {label}
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} style={style}>
          {(t.options ?? []).map((o) => (
            <option key={o} value={o}>
              {OPTION_LABELS[o] ? (lang === "es" ? OPTION_LABELS[o][0] : OPTION_LABELS[o][1]) : o}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (t.type === "int_range") {
    const pair = Array.isArray(value) ? (value as number[]) : [t.min ?? 0, t.max ?? 0];
    return (
      <div className="field">
        <span>
          {label}
          {bounds}
        </span>
        <div className="range-pair">
          <input
            type="number"
            aria-label={`${label} (min)`}
            value={pair[0]}
            min={t.min}
            max={t.max}
            onChange={(e) => onChange([Math.trunc(Number(e.target.value)), pair[1]])}
            style={style}
          />
          <span aria-hidden="true">–</span>
          <input
            type="number"
            aria-label={`${label} (max)`}
            value={pair[1]}
            min={t.min}
            max={t.max}
            onChange={(e) => onChange([pair[0], Math.trunc(Number(e.target.value))])}
            style={style}
          />
        </div>
      </div>
    );
  }
  return (
    <label className="field">
      {label}
      {bounds}
      <input
        type="number"
        value={typeof value === "number" ? value : ""}
        min={t.min}
        max={t.max}
        step={t.type === "int" ? 1 : "any"}
        onChange={(e) => onChange(t.type === "int" ? Math.trunc(Number(e.target.value)) : Number(e.target.value))}
        style={style}
      />
    </label>
  );
}
