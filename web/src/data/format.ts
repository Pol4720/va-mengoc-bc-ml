// Locale-aware number formatting consistent with the manuscripts (siunitx settings):
// Spanish uses a decimal comma and groups only numbers of five or more digits.

import { isSuppressed, num, type Cell } from "./bundle";

export type Lang = "es" | "en";

const cache = new Map<string, Intl.NumberFormat>();

function formatter(lang: Lang, digits: number): Intl.NumberFormat {
  const key = `${lang}:${digits}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(lang === "es" ? "es-ES" : "en-GB", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    cache.set(key, f);
  }
  return f;
}

export function fmt(v: Cell | undefined, lang: Lang, digits = 0): string {
  if (isSuppressed(v)) return String(v);
  const x = num(v);
  if (!Number.isFinite(x)) return "—";
  return formatter(lang, digits).format(x);
}

export function fmtPct(v: Cell | undefined, lang: Lang, digits = 1): string {
  const s = fmt(v, lang, digits);
  if (s === "—" || isSuppressed(v)) return s;
  return lang === "es" ? `${s} %` : `${s}%`;
}

export function fmtCI(est: Cell | undefined, lo: Cell | undefined, hi: Cell | undefined, lang: Lang, digits = 2): string {
  const e = fmt(est, lang, digits);
  if (e === "—") return e;
  return `${e} (${fmt(lo, lang, digits)}–${fmt(hi, lang, digits)})`;
}

export function fmtP(v: Cell | undefined, lang: Lang): string {
  const x = num(v);
  if (!Number.isFinite(x)) return "—";
  if (x < 0.001) return `<${fmt(0.001, lang, 3)}`;
  return fmt(Math.min(x, 1), lang, 3);
}
