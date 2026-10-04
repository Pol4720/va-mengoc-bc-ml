// Client for the local lab API (`vamengoc serve`). The token is kept in memory only.

import { validateBundle, type Bundle } from "./bundle";

export const DEFAULT_API = "http://127.0.0.1:8765";

export interface Tunable {
  path: string;
  type: "enum" | "int" | "float" | "int_range" | "bool";
  options?: string[];
  min?: number;
  max?: number;
  es: string;
  en: string;
  value: unknown;
}

export interface Health {
  status: string;
  version: string;
  raw_data_present: boolean;
  releases: string[];
}

export interface JobStep {
  step: string;
  t?: string;
  rows_in?: number | null;
  rows_out?: number | null;
  detail?: string;
  [k: string]: unknown;
}

export interface Job {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  created: string;
  finished: string | null;
  steps: JobStep[];
  error: string | null;
  verification: { ok: boolean; errors: string[]; files: number } | null;
  has_bundle: boolean;
}

export interface RunRequest {
  source: "synthetic" | "raw";
  overrides: Record<string, unknown>;
  synthetic_scale: number;
  synthetic_seed: number;
  regenerate_synthetic: boolean;
}

export class LabClient {
  constructor(
    private readonly base: string,
    private readonly token: string,
  ) {}

  private url(path: string): string {
    return `${this.base.replace(/\/+$/, "")}${path}`;
  }

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(this.url(path), {
      ...init,
      headers: { "Content-Type": "application/json", "X-Lab-Token": this.token, ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = `${res.status}`;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (body.detail) detail = `${res.status}: ${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)}`;
      } catch {
        // non-JSON error body
      }
      throw new Error(detail);
    }
    return (await res.json()) as T;
  }

  async health(): Promise<Health> {
    const res = await fetch(this.url("/api/health"));
    if (!res.ok) throw new Error(`${res.status}`);
    return (await res.json()) as Health;
  }

  tunables(): Promise<{ tunables: Tunable[] }> {
    return this.req("/api/tunables");
  }

  submit(body: RunRequest): Promise<Job> {
    return this.req("/api/runs", { method: "POST", body: JSON.stringify(body) });
  }

  job(id: string): Promise<Job> {
    return this.req(`/api/runs/${encodeURIComponent(id)}`);
  }

  async bundle(id: string): Promise<Bundle> {
    return validateBundle(await this.req<unknown>(`/api/runs/${encodeURIComponent(id)}/bundle`));
  }
}

/** Nested overrides object from dotted paths, keeping only values that differ from the defaults. */
export function buildOverrides(values: Record<string, unknown>, defaults: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [path, v] of Object.entries(values)) {
    if (JSON.stringify(v) === JSON.stringify(defaults[path])) continue;
    const parts = path.split(".");
    let node = out;
    for (const p of parts.slice(0, -1)) {
      node[p] = (node[p] as Record<string, unknown> | undefined) ?? {};
      node = node[p] as Record<string, unknown>;
    }
    const last = parts[parts.length - 1];
    if (last) node[last] = v;
  }
  return out;
}

/** Validate a user-entered value against a tunable's type and bounds; returns an error message or null. */
export function checkValue(t: Tunable, v: unknown): string | null {
  const inRange = (x: number) => (t.min === undefined || x >= t.min) && (t.max === undefined || x <= t.max);
  switch (t.type) {
    case "bool":
      return typeof v === "boolean" ? null : "bool";
    case "enum":
      return typeof v === "string" && (t.options ?? []).includes(v) ? null : "enum";
    case "int":
      return typeof v === "number" && Number.isInteger(v) && inRange(v) ? null : "range";
    case "float":
      return typeof v === "number" && Number.isFinite(v) && inRange(v) ? null : "range";
    case "int_range": {
      if (!Array.isArray(v) || v.length !== 2) return "pair";
      const [a, b] = v as number[];
      if (!Number.isInteger(a) || !Number.isInteger(b) || !inRange(a as number) || !inRange(b as number)) return "range";
      return (a as number) <= (b as number) ? null : "order";
    }
    default:
      return "type";
  }
}
