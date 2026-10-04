// Bilingual text. Every string is written in both languages at the point of use (tr(es, en)), so
// a missing translation is a type error rather than a silent fallback.

import { createContext, useContext } from "react";
import type { Bundle } from "./data/bundle";
import type { Lang } from "./data/format";

export interface LangApi {
  lang: Lang;
  tr: (es: string, en: string) => string;
}

export function makeLang(lang: Lang): LangApi {
  return { lang, tr: (es, en) => (lang === "es" ? es : en) };
}

export const LangContext = createContext<LangApi>(makeLang("es"));

export function useLang(): LangApi {
  return useContext(LangContext);
}

const LANG_KEY = "vamengoc.lang";

export function loadLang(): Lang {
  try {
    const v = window.localStorage.getItem(LANG_KEY);
    if (v === "es" || v === "en") return v;
  } catch {
    // storage unavailable
  }
  return typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("en") ? "en" : "es";
}

export function saveLang(lang: Lang): void {
  try {
    window.localStorage.setItem(LANG_KEY, lang);
  } catch {
    // storage unavailable
  }
}

/** Comparator designs of the disproportionality analysis (same wording as the manuscripts). */
export const DESIGN_LABELS: Record<string, [string, string]> = {
  primary_all_other_vaccines: ["Principal: resto de vacunas", "Primary: all other vaccines"],
  infant_active_comparator: ["Lactantes <12 meses, comparador activo", "Infants <12 months, active comparator"],
  excluding_coadministration: ["Solo notificaciones de una vacuna", "Single-vaccine reports only"],
  excluding_pentavalent_masking: [
    "Comparador sin PENTA-L (enmascaramiento)",
    "Comparator without PENTA-L (masking)",
  ],
};

export const SENSITIVITY_LABELS: Record<string, [string, string]> = {
  primary: ["GEE principal", "Primary GEE"],
  exact_links_only: ["Solo enlaces exactos", "Exact lot links only"],
  excluding_coadministration: ["Excluyendo coadministración", "Excluding co-administration"],
  keeping_temporally_implausible: ["Conservando fechas inverosímiles", "Keeping implausible dates"],
  mixed: ["Bayesiano, intercepto aleatorio", "Bayesian random intercept"],
  lot_level: ["Cuasibinomial por lote", "Lot-level quasi-binomial"],
};

export function pick(pair: [string, string] | undefined, lang: Lang, fallback: string): string {
  if (!pair) return fallback;
  return lang === "es" ? pair[0] : pair[1];
}

export function eventLabel(b: Bundle, event: string, lang: Lang): string {
  const e = b.labels.events[event];
  if (!e) return event.replace(/^ev_/, "").replace(/_/g, " ");
  return lang === "es" ? e.label_es : e.label_en;
}

export function attributeLabel(b: Bundle, attribute: string, lang: Lang): string {
  const name = attribute.replace(/^z_/, "");
  return b.labels.attributes[lang]?.[name] ?? name;
}

export function outcomeLabel(b: Bundle, outcome: string, lang: Lang): string {
  return b.labels.outcomes[lang]?.[outcome] ?? eventLabel(b, outcome, lang);
}

const TERM_PREFIXES: Record<string, [string, string]> = {
  age_months_log: ["Edad (log meses)", "Age (log months)"],
  female: ["Sexo femenino", "Female sex"],
  coadministered: ["Coadministración", "Co-administration"],
  n_events: ["Número de eventos", "Number of events"],
};

/** Label of a term of the hospitalisation model (vaccines, regions, events, covariates). */
export function termLabel(b: Bundle, term: string, lang: Lang): string {
  const fixed = TERM_PREFIXES[term];
  if (fixed) return lang === "es" ? fixed[0] : fixed[1];
  if (term.startsWith("vac_")) return `${lang === "es" ? "Vacuna" : "Vaccine"} ${term.slice(4)}`;
  if (term.startsWith("region_")) return `${lang === "es" ? "Región" : "Region"} ${term.slice(7)}`;
  if (term.startsWith("ev_")) return eventLabel(b, term, lang);
  return term;
}
