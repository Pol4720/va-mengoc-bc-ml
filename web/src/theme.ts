// Theme state (auto / light / dark) and chart tokens read from the CSS custom properties, so the
// charts and the page always use the same selected light or dark steps.

import { createContext, useContext } from "react";

export type ThemeChoice = "auto" | "light" | "dark";

export interface Tokens {
  mode: "light" | "dark";
  surface: string;
  surface2: string;
  ink: string;
  ink2: string;
  muted: string;
  axisLabel: string;
  grid: string;
  axis: string;
  s1: string;
  s2: string;
  s3: string;
  deemph: string;
  critical: string;
  serious: string;
  warning: string;
  good: string;
  seq: string[];
  divNeg: string;
  divMid: string;
  divPos: string;
  band: string;
  band2: string;
  font: string;
  reducedMotion: boolean;
}

/** Light-mode values, used when CSS variables are unavailable (tests, server rendering). */
export const FALLBACK_TOKENS: Tokens = {
  mode: "light",
  surface: "#fcfcfb",
  surface2: "#f3f2ee",
  ink: "#0b0b0b",
  ink2: "#52514e",
  muted: "#6f6d68",
  axisLabel: "#898781",
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  s1: "#2a78d6",
  s2: "#eb6834",
  s3: "#1baf7a",
  deemph: "#b9b8b0",
  critical: "#d03b3b",
  serious: "#ec835a",
  warning: "#fab219",
  good: "#0ca30c",
  seq: ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],
  divNeg: "#2a78d6",
  divMid: "#f0efec",
  divPos: "#e34948",
  band: "rgba(42, 120, 214, 0.1)",
  band2: "rgba(42, 120, 214, 0.2)",
  font: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  reducedMotion: false,
};

const STORAGE_KEY = "vamengoc.theme";

export function loadThemeChoice(): ThemeChoice {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function saveThemeChoice(choice: ThemeChoice): void {
  try {
    if (choice === "auto") window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // storage unavailable (private mode, blocked): the choice lasts for this page view only
  }
}

export function applyThemeChoice(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export function readTokens(): Tokens {
  if (typeof window === "undefined" || typeof getComputedStyle === "undefined") return FALLBACK_TOKENS;
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string): string => cs.getPropertyValue(name).trim() || fallback;
  const f = FALLBACK_TOKENS;
  const surface = v("--surface", f.surface);
  return {
    mode: isDark(surface) ? "dark" : "light",
    surface,
    surface2: v("--surface-2", f.surface2),
    ink: v("--ink", f.ink),
    ink2: v("--ink-2", f.ink2),
    muted: v("--muted", f.muted),
    axisLabel: v("--axis-label", f.axisLabel),
    grid: v("--grid", f.grid),
    axis: v("--axis", f.axis),
    s1: v("--s1", f.s1),
    s2: v("--s2", f.s2),
    s3: v("--s3", f.s3),
    deemph: v("--deemph", f.deemph),
    critical: v("--critical", f.critical),
    serious: v("--serious", f.serious),
    warning: v("--warning", f.warning),
    good: v("--good", f.good),
    seq: ["--seq-100", "--seq-250", "--seq-400", "--seq-550", "--seq-700"].map((n, i) => v(n, f.seq[i] ?? f.s1)),
    divNeg: v("--div-neg", f.divNeg),
    divMid: v("--div-mid", f.divMid),
    divPos: v("--div-pos", f.divPos),
    band: v("--band", f.band),
    band2: v("--band-2", f.band2),
    font: v("--font", f.font),
    reducedMotion: prefersReducedMotion(),
  };
}

/** True when a #rrggbb colour is dark (relative luminance below 0.2). */
export function isDark(hex: string): boolean {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m || !m[1]) return false;
  const n = Number.parseInt(m[1], 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  const lum = 0.2126 * (ch[0] ?? 0) + 0.7152 * (ch[1] ?? 0) + 0.0722 * (ch[2] ?? 0);
  return lum < 0.2;
}

export const TokensContext = createContext<Tokens>(FALLBACK_TOKENS);

export function useTokens(): Tokens {
  return useContext(TokensContext);
}
