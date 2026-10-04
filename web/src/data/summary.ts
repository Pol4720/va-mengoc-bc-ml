// Headline figures derived from the bundle with the same definitions as the manuscripts
// (release/builder.py): prespecified signals in the primary design, robust signals present in
// every design, FDR-significant single-exposure associations.

import { bool, num, object, sum, table, type Bundle } from "./bundle";

export const PRIMARY_DESIGN = "primary_all_other_vaccines";
export const FDR_ALPHA = 0.05;

export interface RatesTrend {
  estimable?: boolean;
  first_year?: number;
  last_year?: number;
  rr_per_year?: number;
  rr_lo?: number;
  rr_hi?: number;
  p_value?: number;
  pooled_rate_per_100k?: number;
  pooled_rate_lo?: number;
  pooled_rate_hi?: number;
}

export interface SeriousnessMetrics {
  n_train: number;
  n_test: number;
  metrics: Record<string, { auroc: number; auprc: number; brier: number; cal_slope: number; cal_intercept: number }>;
}

export interface LinkageSummary {
  n_target_reports: number;
  n_linked: number;
  link_rate: number;
  n_distinct_lots_linked: number;
  temporal_implausible?: number;
  by_level?: Record<string, number | string>;
}

export interface Changepoints {
  breaks: string[];
  segments: { start: string; end: string; months: number; mean_count: number }[];
}

export function p1Summary(b: Bundle) {
  const years = table(b, "p1_reports_by_year");
  const dp = table(b, "p1_disproportionality");
  const prim = dp.filter((r) => r.design === PRIMARY_DESIGN);
  const flagged = prim.filter((r) => bool(r.signal_primary)).map((r) => String(r.event));
  const designs = [...new Set(dp.map((r) => String(r.design)))];
  const robust = flagged.filter((e) =>
    designs.every((d) => dp.some((r) => r.design === d && r.event === e && bool(r.signal_primary))),
  );
  const expected = flagged.filter((e) => !!b.labels.events[e]?.expected);
  const trend = object<RatesTrend>(b, "p1_rates_trend") ?? {};
  const lca = object<{ best_k?: number; bootstrap_ari_median?: number }>(b, "p1_lca_summary") ?? {};
  const ser = object<SeriousnessMetrics>(b, "p1_seriousness_metrics");
  const yr = years.map((r) => num(r.analytic_year)).filter(Number.isFinite);
  return {
    allReports: sum(years, "n_reports"),
    targetReports: sum(years, "n_target"),
    firstYear: yr.length ? Math.min(...yr) : NaN,
    lastYear: yr.length ? Math.max(...yr) : NaN,
    nEvents: Object.keys(b.labels.events).length,
    designs,
    flagged,
    robust,
    expected,
    emerging: flagged.filter((e) => !expected.includes(e)),
    trend,
    bestK: lca.best_k,
    ari: lca.bootstrap_ari_median,
    auroc: ser?.metrics.logistic_test?.auroc,
    aurocGbm: ser?.metrics.gbm_test?.auroc,
  };
}

export function p2Summary(b: Bundle) {
  const link = object<LinkageSummary>(b, "p2_linkage_summary");
  const frame = object<{ n_reports?: number; n_lots?: number }>(b, "p2_qc_frame_summary") ?? {};
  const mspc = object<{ n_lots?: number; n_flagged?: number }>(b, "p2_mspc_summary") ?? {};
  const primary = table(b, "p2_gee_primary");
  const single = primary.filter((r) => r.model === "single" && !bool(r.negative_control));
  const significant = single.filter((r) => num(r.p_bh) < FDR_ALPHA);
  const cap = table(b, "p2_capability").filter((r) => r.period === "all" && bool(r.estimable));
  return {
    nLots: num(mspc.n_lots),
    lotsFlagged: num(mspc.n_flagged),
    linkRate: link ? link.link_rate : NaN,
    nLinked: link ? link.n_linked : NaN,
    nTargetReports: link ? link.n_target_reports : NaN,
    nAnalysed: num(frame.n_reports),
    nLotsAnalysed: num(frame.n_lots),
    nAssociations: single.length,
    significant,
    capabilityBelow1: cap.filter((r) => num(r.ppk) < 1).map((r) => String(r.attribute)),
    nAttributes: cap.length,
  };
}

export function dqSummary(b: Bundle) {
  const comp = table(b, "dq_completeness");
  const plaus = table(b, "dq_plausibility");
  const flagged = sum(plaus, "n_flagged");
  const records = new Map<number, number>();
  for (const r of plaus) records.set(num(r.file_year), num(r.n_records));
  const nRecords = [...records.values()].reduce((a, v) => a + (Number.isFinite(v) ? v : 0), 0);
  const pct = comp.map((r) => num(r.pct_present)).filter(Number.isFinite);
  return {
    nRecords,
    nChecks: new Set(plaus.map((r) => String(r.check))).size,
    flagged,
    meanCompleteness: pct.length ? pct.reduce((a, v) => a + v, 0) / pct.length : NaN,
    nFiles: records.size,
  };
}

/** Lower end of the completeness colour scale: 90 % or below, in steps of 5, so near-complete fields stay distinguishable. */
export function completenessFloor(values: number[]): number {
  const v = values.filter(Number.isFinite);
  if (!v.length) return 0;
  return Math.max(0, Math.min(90, Math.floor(Math.min(...v) / 5) * 5));
}
