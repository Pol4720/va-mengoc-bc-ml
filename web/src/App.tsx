// Application shell: loads the bundle, hash routing, language and theme toggles, synthetic-data
// banner and provenance footer.

import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Segmented } from "./components/ui";
import { loadBundle, type Bundle } from "./data/bundle";
import type { Lang } from "./data/format";
import { LangContext, loadLang, makeLang, saveLang } from "./i18n";
import { Home } from "./pages/Home";
import { BundleContext, parseRoute, type Page } from "./state";
import {
  applyThemeChoice,
  loadThemeChoice,
  readTokens,
  saveThemeChoice,
  TokensContext,
  type ThemeChoice,
  type Tokens,
} from "./theme";

const NAV: { page: Page; es: string; en: string; hash: string }[] = [
  { page: "home", es: "Inicio", en: "Home", hash: "#/" },
  { page: "pv", es: "Farmacovigilancia", en: "Pharmacovigilance", hash: "#/pv" },
  { page: "lots", es: "Calidad de lotes", en: "Lot quality", hash: "#/lots" },
  { page: "data", es: "Calidad de datos", en: "Data quality", hash: "#/data" },
  { page: "slides", es: "Presentaciones", en: "Slides", hash: "#/slides" },
  { page: "lab", es: "Laboratorio", en: "Lab", hash: "#/lab" },
];

const REPO = "https://github.com/Pol4720/va-mengoc-bc-ml";

// Pages with charts load on demand, so the landing page does not download ECharts.
const Pharmacovigilance = lazy(() => import("./pages/Pharmacovigilance").then((m) => ({ default: m.Pharmacovigilance })));
const LotQuality = lazy(() => import("./pages/LotQuality").then((m) => ({ default: m.LotQuality })));
const DataQuality = lazy(() => import("./pages/DataQuality").then((m) => ({ default: m.DataQuality })));
const Lab = lazy(() => import("./pages/Lab").then((m) => ({ default: m.Lab })));
const Slides = lazy(() => import("./pages/Slides").then((m) => ({ default: m.Slides })));

function useHashRoute() {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return useMemo(() => parseRoute(hash), [hash]);
}

function useTheme(): [ThemeChoice, (c: ThemeChoice) => void, Tokens] {
  const [choice, setChoice] = useState<ThemeChoice>(() => loadThemeChoice());
  const [tokens, setTokens] = useState<Tokens>(() => readTokens());
  const change = useCallback((c: ThemeChoice) => {
    applyThemeChoice(c);
    saveThemeChoice(c);
    setChoice(c);
    setTokens(readTokens());
  }, []);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const rm = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const on = () => setTokens(readTokens());
    mq?.addEventListener?.("change", on);
    rm?.addEventListener?.("change", on);
    return () => {
      mq?.removeEventListener?.("change", on);
      rm?.removeEventListener?.("change", on);
    };
  }, []);
  return [choice, change, tokens];
}

function ThemeIcon({ choice }: { choice: ThemeChoice }) {
  if (choice === "light")
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="3.2" fill="currentColor" />
        <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6 13 13M3 13l1.4-1.4M11.6 4.4 13 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    );
  if (choice === "dark")
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M13.5 10.2A6 6 0 0 1 5.8 2.5a6 6 0 1 0 7.7 7.7Z" fill="currentColor" />
      </svg>
    );
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 2a6 6 0 0 1 0 12Z" fill="currentColor" />
    </svg>
  );
}

function Loading({ text }: { text: string }) {
  return (
    <p style={{ color: "var(--muted)", display: "flex", gap: 8, alignItems: "center" }} role="status">
      <span className="spinner" aria-hidden="true" /> {text}
    </p>
  );
}

export function App() {
  const route = useHashRoute();
  const [lang, setLangState] = useState<Lang>(() => loadLang());
  const L = useMemo(() => makeLang(lang), [lang]);
  const [choice, setChoice, tokens] = useTheme();
  const [base, setBase] = useState<Bundle | null>(null);
  const [lab, setLab] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadBundle()
      .then(setBase)
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
    saveLang(lang);
  }, [lang]);
  useEffect(() => {
    window.scrollTo?.({ top: 0 });
  }, [route.page]);

  const setLabBundle = useCallback((b: Bundle | null) => setLab(b), []);
  const bundle = lab ?? base;
  const state = useMemo(
    () => (bundle ? { bundle, origin: lab ? (lab.meta.lab_job ?? "lab") : "release", setLabBundle } : null),
    [bundle, lab, setLabBundle],
  );
  const { tr } = L;
  const nextTheme: Record<ThemeChoice, ThemeChoice> = { auto: "light", light: "dark", dark: "auto" };
  const themeName = { auto: tr("automático", "automatic"), light: tr("claro", "light"), dark: tr("oscuro", "dark") }[choice];

  useEffect(() => {
    const titles: Record<Page, string> = {
      home: tr("Inicio", "Home"),
      pv: tr("Farmacovigilancia", "Pharmacovigilance"),
      lots: tr("Calidad de lotes", "Lot quality"),
      data: tr("Calidad de datos", "Data quality"),
      lab: tr("Laboratorio", "Lab"),
      slides: tr("Presentaciones", "Slides"),
    };
    document.title = `${titles[route.page]} · VA-MENGOC-BC`;
  }, [route.page, tr]);

  let content;
  if (error) {
    content = (
      <div className="notice" role="alert">
        <div className="grow">
          <strong>{tr("No se pudo cargar el release.", "The release could not be loaded.")}</strong> {error}
        </div>
      </div>
    );
  } else if (!state) {
    content = <Loading text={tr("Cargando resultados…", "Loading results…")} />;
  } else {
    const page = route.page;
    content =
      page === "pv" ? (
        <Pharmacovigilance />
      ) : page === "lots" ? (
        <LotQuality />
      ) : page === "data" ? (
        <DataQuality />
      ) : page === "lab" ? (
        <Lab />
      ) : page === "slides" ? (
        <Slides deckId={route.deck} slide={route.slide} />
      ) : (
        <Home />
      );
  }

  const meta = state?.bundle.meta;
  return (
    <LangContext.Provider value={L}>
      <TokensContext.Provider value={tokens}>
        <div className="app">
          <a className="skip-link" href="#main">
            {tr("Saltar al contenido", "Skip to content")}
          </a>
          <header className="topbar">
            <div className="topbar-inner">
              <a className="brand" href="#/">
                <span className="brand-mark" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 32 32">
                    <path d="M7 24V8l9 11 9-11v16" stroke="white" strokeWidth="3.4" fill="none" strokeLinejoin="round" strokeLinecap="round" />
                  </svg>
                </span>
                <span>
                  VA-MENGOC-BC
                  <small>{tr("Evidencia reproducible", "Reproducible evidence")}</small>
                </span>
              </a>
              <nav className="nav" aria-label={tr("Secciones", "Sections")}>
                {NAV.map((n) => (
                  <a key={n.page} href={n.hash} aria-current={route.page === n.page ? "page" : undefined}>
                    {lang === "es" ? n.es : n.en}
                  </a>
                ))}
              </nav>
              <div className="toolbar">
                <Segmented
                  label={tr("Idioma", "Language")}
                  value={lang}
                  onChange={(v) => setLangState(v as Lang)}
                  options={[
                    { value: "es", label: "ES", title: "Español" },
                    { value: "en", label: "EN", title: "English" },
                  ]}
                />
                <button
                  type="button"
                  className="btn small"
                  onClick={() => setChoice(nextTheme[choice])}
                  aria-label={tr(`Tema: ${themeName}. Cambiar tema`, `Theme: ${themeName}. Change theme`)}
                  title={tr(`Tema ${themeName}`, `${themeName} theme`)}
                >
                  <ThemeIcon choice={choice} />
                  <span className="theme-label">{themeName}</span>
                </button>
              </div>
            </div>
          </header>
          <main id="main" tabIndex={-1}>
            {meta?.synthetic ? (
              <div className="notice synthetic" role="note">
                <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M8 1.5 15 14H1L8 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                  <path d="M8 6v3.5M8 11.5v.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
                <div className="grow">
                  <strong>{tr("Datos sintéticos.", "Synthetic data.")}</strong>{" "}
                  {tr(
                    "Estas cifras demuestran el pipeline con datos simulados; no son resultados reales sobre VA-MENGOC-BC.",
                    "These figures demonstrate the pipeline with simulated data; they are not real results about VA-MENGOC-BC.",
                  )}
                </div>
              </div>
            ) : null}
            {state ? (
              <BundleContext.Provider value={state}>
                <Suspense fallback={<Loading text={tr("Cargando…", "Loading…")} />}>{content}</Suspense>
              </BundleContext.Provider>
            ) : (
              content
            )}
          </main>
          <footer className="footer">
            <div className="footer-inner">
              <span>
                © {new Date().getFullYear()} R. A. Matos Arderí, A. Ponce González · Instituto Finlay de Vacunas
              </span>
              {meta ? (
                <>
                  <span>
                    {tr("Ejecución", "Run")} <code>{meta.run_id}</code>
                  </span>
                  <span>
                    {tr("Código", "Code")} <code>v{meta.code_version}</code>
                    {meta.git_commit ? (
                      <>
                        {" · "}
                        <a href={`${REPO}/commit/${meta.git_commit}`}>
                          <code>{meta.git_commit.slice(0, 7)}</code>
                        </a>
                      </>
                    ) : null}
                  </span>
                  <span>
                    {tr("Semilla", "Seed")} <code>{meta.seed}</code> · {tr("celda mínima", "minimum cell")} <code>{meta.sdc.min_cell}</code>
                  </span>
                </>
              ) : null}
              <a href={REPO}>{tr("Código fuente", "Source code")}</a>
            </div>
          </footer>
        </div>
      </TokensContext.Provider>
    </LangContext.Provider>
  );
}
