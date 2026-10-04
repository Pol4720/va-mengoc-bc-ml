// Types and helpers for the disclosure-controlled results bundle (release/*/web/bundle.json).
// Every value shown by the app comes from this bundle; the app never sees individual records.

export type Cell = string | number | boolean | null;
export type Row = Record<string, Cell>;

export interface BundleMeta {
  data_origin: "synthetic" | "public" | string;
  synthetic: boolean;
  generated_utc: string;
  run_id: string;
  code_version: string;
  git_commit: string | null;
  seed: number;
  study_years: [number, number];
  target_vaccine: string;
  sdc: { min_cell: number; token: string; secondary_suppression: boolean; release_lot_values: string };
  lab_job?: string;
}

export interface EventLabel {
  label_en: string;
  label_es: string;
  domain: string;
  class: string;
  expected?: boolean;
}

export interface Bundle {
  meta: BundleMeta;
  labels: {
    events: Record<string, EventLabel>;
    attributes: { en: Record<string, string>; es: Record<string, string> };
    outcomes: { en: Record<string, string>; es: Record<string, string> };
  };
  tables: Record<string, Row[]>;
  objects: Record<string, unknown>;
}

/** Disclosure-control markers: primary suppression ("<5") and complementary suppression ("[c]"). */
export const SECONDARY = "[c]";

export function isSuppressed(v: Cell | undefined, token = "<5"): boolean {
  return typeof v === "string" && (v === token || v === SECONDARY);
}

/** Numeric value of a cell, or NaN for missing, suppressed or non-numeric cells. */
export function num(v: Cell | undefined): number {
  if (typeof v === "number") return v;
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "string" && v.trim() !== "" && !isSuppressed(v)) {
    const x = Number(v);
    return Number.isFinite(x) ? x : Number.NaN;
  }
  return Number.NaN;
}

export function bool(v: Cell | undefined): boolean {
  return v === true || v === "True" || v === "true" || v === 1;
}

export function table(b: Bundle, name: string): Row[] {
  return b.tables[name] ?? [];
}

export function object<T>(b: Bundle, name: string): T | undefined {
  return b.objects[name] as T | undefined;
}

export function sum(rows: Row[], col: string): number {
  return rows.reduce((acc, r) => {
    const x = num(r[col]);
    return Number.isFinite(x) ? acc + x : acc;
  }, 0);
}

export async function loadBundle(url = "data/bundle.json"): Promise<Bundle> {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`bundle not found (${res.status})`);
  return validateBundle(await res.json());
}

/** Minimal structural validation so a malformed bundle fails loudly instead of rendering nonsense. */
export function validateBundle(raw: unknown): Bundle {
  const b = raw as Partial<Bundle>;
  if (!b || typeof b !== "object" || !b.meta || !b.tables || !b.labels) {
    throw new Error("invalid bundle: missing meta, labels or tables");
  }
  if (!Array.isArray(b.meta.study_years) || typeof b.meta.data_origin !== "string") {
    throw new Error("invalid bundle: malformed meta");
  }
  const labels = b.labels as Partial<Bundle["labels"]>;
  return {
    ...(b as Bundle),
    labels: {
      events: labels.events ?? {},
      attributes: labels.attributes ?? { en: {}, es: {} },
      outcomes: labels.outcomes ?? { en: {}, es: {} },
    },
    objects: b.objects ?? {},
  };
}
