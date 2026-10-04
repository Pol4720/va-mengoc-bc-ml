// Client-side re-thresholding of the released disproportionality measures.
// The app never recomputes measures from counts (b, c, d are not released); it only applies a
// different decision rule to the released ROR, PRR, IC and EBGM bounds, exactly as the pipeline does.

import { bool, isSuppressed, num, type Row } from "./bundle";

export type Criterion = "ic" | "ror" | "prr" | "ebgm" | "consensus2";

export interface Thresholds {
  minReports: number;
  rorLower: number;
  prr: number;
  prrChi2: number;
  ic025: number;
  eb05: number;
}

export const DEFAULT_THRESHOLDS: Thresholds = {
  minReports: 3,
  rorLower: 1,
  prr: 2,
  prrChi2: 4,
  ic025: 0,
  eb05: 2,
};

export interface SignalRow {
  event: string;
  a: number | null; // null when suppressed or withheld
  withheld: boolean;
  ror: number;
  rorLo: number;
  rorHi: number;
  ic025: number;
  eb05: number;
  methods: number;
  signal: boolean;
  /** Decision of the pipeline itself for its prespecified criterion (for comparison). */
  pipelineSignal: boolean;
}

export function evaluate(row: Row, criterion: Criterion, t: Thresholds): SignalRow {
  const a = num(row.a);
  const withheld = isSuppressed(row.a) || Number.isNaN(num(row.ror));
  const enough = Number.isFinite(a) && a >= t.minReports;
  const rorLo = num(row.ror_lo);
  const prr = num(row.prr);
  const chi2 = num(row.chi2_yates);
  const ic025 = num(row.ic025);
  const eb05 = num(row.eb05);
  const flags = {
    ror: enough && rorLo > t.rorLower,
    prr: enough && prr >= t.prr && chi2 >= t.prrChi2,
    ic: enough && ic025 > t.ic025,
    ebgm: enough && eb05 >= t.eb05,
  };
  const methods = Object.values(flags).filter(Boolean).length;
  const signal = !withheld && (criterion === "consensus2" ? methods >= 2 : flags[criterion]);
  return {
    event: String(row.event),
    a: Number.isFinite(a) ? a : null,
    withheld,
    ror: num(row.ror),
    rorLo,
    rorHi: num(row.ror_hi),
    ic025,
    eb05,
    methods,
    signal,
    pipelineSignal: bool(row.signal_primary),
  };
}

export function evaluateDesign(rows: Row[], design: string, criterion: Criterion, t: Thresholds): SignalRow[] {
  return rows.filter((r) => r.design === design).map((r) => evaluate(r, criterion, t));
}
