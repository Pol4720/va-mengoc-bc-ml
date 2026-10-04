import { describe, expect, it } from "vitest";
import { fixtureBundle } from "../test/fixture";
import { bool, isSuppressed, num, SECONDARY, sum, validateBundle } from "./bundle";
import { fmt, fmtCI, fmtP, fmtPct } from "./format";
import { buildOverrides, checkValue, type Tunable } from "./lab";
import { DEFAULT_THRESHOLDS, evaluate, evaluateDesign } from "./signals";
import { completenessFloor, dqSummary, p1Summary, p2Summary } from "./summary";

describe("bundle helpers", () => {
  it("recognises both suppression markers", () => {
    expect(isSuppressed("<5")).toBe(true);
    expect(isSuppressed(SECONDARY)).toBe(true);
    expect(isSuppressed("5")).toBe(false);
    expect(isSuppressed(4)).toBe(false);
  });

  it("parses numbers and never turns markers into values", () => {
    expect(num(3)).toBe(3);
    expect(num("2.5")).toBe(2.5);
    expect(num("<5")).toBeNaN();
    expect(num("[c]")).toBeNaN();
    expect(num(null)).toBeNaN();
    expect(num("")).toBeNaN();
    expect(num("abc")).toBeNaN();
    expect(num(true)).toBe(1);
  });

  it("reads booleans written by pandas", () => {
    expect(bool(true)).toBe(true);
    expect(bool("True")).toBe(true);
    expect(bool(1)).toBe(true);
    expect(bool("False")).toBe(false);
    expect(bool(null)).toBe(false);
  });

  it("sums only released numeric cells", () => {
    expect(sum([{ n: 3 }, { n: "<5" }, { n: "4" }, { n: null }], "n")).toBe(7);
  });

  it("rejects malformed bundles loudly", () => {
    expect(() => validateBundle(null)).toThrow(/invalid bundle/);
    expect(() => validateBundle({ meta: {}, labels: {}, tables: {} })).toThrow(/malformed meta/);
    const b = validateBundle({ ...fixtureBundle(), objects: undefined });
    expect(b.objects).toEqual({});
  });
});

describe("formatting", () => {
  it("uses a decimal comma in Spanish and a point in English", () => {
    expect(fmt(1234.5, "es", 1)).toBe("1234,5");
    expect(fmt(12345.5, "es", 1)).toBe("12.345,5");
    expect(fmt(1234.5, "en", 1)).toBe("1,234.5");
  });

  it("passes suppression markers through and marks missing values", () => {
    expect(fmt("<5", "es")).toBe("<5");
    expect(fmt("[c]", "en")).toBe("[c]");
    expect(fmt(null, "en")).toBe("—");
    expect(fmtPct("<5", "es")).toBe("<5");
  });

  it("formats percentages, intervals and p-values", () => {
    expect(fmtPct(17.25, "es")).toBe("17,3 %");
    expect(fmtPct(17.25, "en")).toBe("17.3%");
    expect(fmtCI(1.234, 1.1, 1.4, "en")).toBe("1.23 (1.10–1.40)");
    expect(fmtCI(null, 1, 2, "en")).toBe("—");
    expect(fmtP(0.0004, "en")).toBe("<0.001");
    expect(fmtP(0.0123, "es")).toBe("0,012");
    expect(fmtP(1.2, "en")).toBe("1.000");
    expect(fmtP(null, "en")).toBe("—");
  });
});

describe("signal re-thresholding", () => {
  const rows = fixtureBundle().tables.p1_disproportionality ?? [];
  const primary = rows.filter((r) => r.design === "primary_all_other_vaccines");

  it("reproduces the prespecified IC criterion", () => {
    const ev = evaluateDesign(rows, "primary_all_other_vaccines", "ic", DEFAULT_THRESHOLDS);
    expect(ev.map((e) => e.signal)).toEqual(ev.map((e) => e.pipelineSignal));
  });

  it("applies each criterion to the released measures only", () => {
    const fever = primary[0]!;
    expect(evaluate(fever, "ror", DEFAULT_THRESHOLDS).signal).toBe(true);
    expect(evaluate(fever, "prr", DEFAULT_THRESHOLDS).signal).toBe(true);
    expect(evaluate(fever, "ebgm", DEFAULT_THRESHOLDS).signal).toBe(false);
    expect(evaluate(fever, "consensus2", DEFAULT_THRESHOLDS).methods).toBe(3);
  });

  it("requires the minimum number of reports", () => {
    const abscess = primary[1]!;
    expect(evaluate(abscess, "ic", DEFAULT_THRESHOLDS).signal).toBe(true);
    expect(evaluate(abscess, "ic", { ...DEFAULT_THRESHOLDS, minReports: 10 }).signal).toBe(false);
  });

  it("never flags a suppressed cell", () => {
    const rash = evaluate(primary[2]!, "consensus2", { ...DEFAULT_THRESHOLDS, minReports: 0 });
    expect(rash.withheld).toBe(true);
    expect(rash.signal).toBe(false);
    expect(rash.a).toBeNull();
  });
});

describe("headline summaries", () => {
  const b = fixtureBundle();

  it("defines robust and expected signals as the manuscripts do", () => {
    const s = p1Summary(b);
    expect(s.targetReports).toBe(20);
    expect(s.allReports).toBe(220);
    expect(s.flagged).toEqual(["ev_fever_39", "ev_abscess"]);
    expect(s.robust).toEqual(["ev_fever_39"]);
    expect(s.expected).toEqual(["ev_fever_39"]);
    expect(s.emerging).toEqual(["ev_abscess"]);
    expect([s.firstYear, s.lastYear]).toEqual([2017, 2018]);
  });

  it("counts FDR-significant single-exposure associations, excluding the negative control", () => {
    const s = p2Summary(b);
    expect(s.nAssociations).toBe(2);
    expect(s.significant.map((r) => r.exposure)).toEqual(["endotoxin"]);
    expect(s.capabilityBelow1).toEqual(["ph"]);
    expect(s.linkRate).toBeCloseTo(0.95);
  });

  it("summarises data quality with suppressed flags counted as zero", () => {
    const s = dqSummary(b);
    expect(s.nRecords).toBe(220);
    expect(s.flagged).toBe(9);
    expect(s.nChecks).toBe(2);
  });

  it("sets the completeness colour floor in steps of five", () => {
    expect(completenessFloor([99.9, 100])).toBe(90);
    expect(completenessFloor([72, 100])).toBe(70);
    expect(completenessFloor([])).toBe(0);
  });
});

describe("lab client helpers", () => {
  const t = (over: Partial<Tunable>): Tunable => ({ path: "a.b", type: "int", es: "", en: "", value: 1, ...over });

  it("sends only changed parameters as a nested object", () => {
    const out = buildOverrides(
      { "analysis.seed": 7, "analysis.qc.ewma_lambda": 0.2, "sdc.min_cell": 5 },
      { "analysis.seed": 1, "analysis.qc.ewma_lambda": 0.2, "sdc.min_cell": 5 },
    );
    expect(out).toEqual({ analysis: { seed: 7 } });
  });

  it("validates values against the whitelist bounds", () => {
    expect(checkValue(t({ min: 1, max: 20 }), 3)).toBeNull();
    expect(checkValue(t({ min: 1, max: 20 }), 30)).toBe("range");
    expect(checkValue(t({ min: 1, max: 20 }), 2.5)).toBe("range");
    expect(checkValue(t({ type: "float", min: 0, max: 1 }), 0.5)).toBeNull();
    expect(checkValue(t({ type: "enum", options: ["x"] }), "y")).toBe("enum");
    expect(checkValue(t({ type: "bool" }), true)).toBeNull();
    expect(checkValue(t({ type: "int_range", min: 2010, max: 2030 }), [2017, 2025])).toBeNull();
    expect(checkValue(t({ type: "int_range", min: 2010, max: 2030 }), [2025, 2017])).toBe("order");
    expect(checkValue(t({ type: "int_range", min: 2010, max: 2030 }), [2017])).toBe("pair");
  });
});
