// Small hand-made bundle for unit tests (no real or synthetic records).

import type { Bundle } from "../data/bundle";

export function fixtureBundle(): Bundle {
  return {
    meta: {
      data_origin: "synthetic",
      synthetic: true,
      generated_utc: "2026-10-04T00:00:00+00:00",
      run_id: "test-run",
      code_version: "0.1.0",
      git_commit: "0123456789abcdef",
      seed: 1,
      study_years: [2017, 2025],
      target_vaccine: "AM-BC",
      sdc: { min_cell: 5, token: "<5", secondary_suppression: true, release_lot_values: "normalized" },
    },
    labels: {
      events: {
        ev_fever_39: { label_en: "Fever ≥39 °C", label_es: "Fiebre ≥39 °C", domain: "systemic", class: "common", expected: true },
        ev_abscess: { label_en: "Abscess", label_es: "Absceso", domain: "local", class: "rare", expected: false },
        ev_rash: { label_en: "Rash", label_es: "Exantema", domain: "allergic", class: "rare", expected: false },
      },
      attributes: { en: { endotoxin: "Endotoxin" }, es: { endotoxin: "Endotoxina" } },
      outcomes: { en: { ev_fever_39: "Fever ≥39 °C" }, es: { ev_fever_39: "Fiebre ≥39 °C" } },
    },
    tables: {
      p1_reports_by_year: [
        { analytic_year: 2017, n_reports: 100, n_target: 20 },
        { analytic_year: 2018, n_reports: 120, n_target: "<5" },
      ],
      p1_disproportionality: [
        { design: "primary_all_other_vaccines", event: "ev_fever_39", a: 50, ror: 2, ror_lo: 1.5, ror_hi: 2.6, prr: 2.1, chi2_yates: 20, ic: 0.8, ic025: 0.4, ic975: 1.1, ebgm: 1.9, eb05: 1.5, signal_primary: true },
        { design: "primary_all_other_vaccines", event: "ev_abscess", a: 8, ror: 5, ror_lo: 2, ror_hi: 12, prr: 4.9, chi2_yates: 9, ic: 1.4, ic025: 0.3, ic975: 2.2, ebgm: 3.5, eb05: 2.1, signal_primary: true },
        { design: "primary_all_other_vaccines", event: "ev_rash", a: "<5", ror: null, ror_lo: null, ror_hi: null, prr: null, chi2_yates: null, ic: null, ic025: null, ic975: null, ebgm: null, eb05: null, signal_primary: false },
        { design: "infant_active_comparator", event: "ev_fever_39", a: 45, ror: 1.8, ror_lo: 1.3, ror_hi: 2.4, prr: 1.7, chi2_yates: 12, ic: 0.6, ic025: 0.2, ic975: 0.9, ebgm: 1.7, eb05: 1.3, signal_primary: true },
        { design: "infant_active_comparator", event: "ev_abscess", a: 6, ror: 1.4, ror_lo: 0.6, ror_hi: 3, prr: 1.4, chi2_yates: 0.5, ic: 0.3, ic025: -0.6, ic975: 1.1, ebgm: 1.2, eb05: 0.7, signal_primary: false },
      ],
      p2_gee_primary: [
        { outcome: "ev_fever_39", exposure: "endotoxin", model: "single", negative_control: false, or_per_sd: 1.3, or_lo: 1.1, or_hi: 1.5, p_value: 0.001, p_bh: 0.004 },
        { outcome: "ev_fever_39", exposure: "ph", model: "single", negative_control: false, or_per_sd: 1.0, or_lo: 0.9, or_hi: 1.1, p_value: 0.8, p_bh: 0.8 },
        { outcome: "ev_fever_39", exposure: "fill_volume", model: "single", negative_control: true, or_per_sd: 0.95, or_lo: 0.85, or_hi: 1.05, p_value: 0.3, p_bh: null },
        { outcome: "ev_fever_39", exposure: "endotoxin", model: "crude", negative_control: false, or_per_sd: 1.32, or_lo: 1.1, or_hi: 1.55, p_value: 0.001, p_bh: null },
      ],
      p2_capability: [
        { attribute: "endotoxin", period: "all", estimable: true, ppk: 1.4 },
        { attribute: "ph", period: "all", estimable: true, ppk: 0.9 },
        { attribute: "ph", period: "2011-2016", estimable: true, ppk: 0.8 },
      ],
      dq_completeness: [
        { file_year: 2017, field: "sex", pct_present: 100 },
        { file_year: 2017, field: "age", pct_present: 96.5 },
      ],
      dq_plausibility: [
        { file_year: 2017, check: "a", n_records: 100, n_flagged: 3 },
        { file_year: 2017, check: "b", n_records: 100, n_flagged: "<5" },
        { file_year: 2018, check: "a", n_records: 120, n_flagged: 6 },
      ],
    },
    objects: {
      p1_rates_trend: { pooled_rate_per_100k: 180, rr_per_year: 1.01, rr_lo: 0.95, rr_hi: 1.07 },
      p1_lca_summary: { best_k: 3, bootstrap_ari_median: 0.9 },
      p2_linkage_summary: { n_target_reports: 200, n_linked: 190, link_rate: 0.95, n_distinct_lots_linked: 40 },
      p2_qc_frame_summary: { n_reports: 180, n_lots: 38 },
      p2_mspc_summary: { n_lots: 120, n_flagged: 4 },
    },
  };
}
