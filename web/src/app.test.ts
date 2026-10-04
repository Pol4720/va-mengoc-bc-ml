import { describe, expect, it, vi } from "vitest";
import { attributeLabel, eventLabel, makeLang, termLabel } from "./i18n";
import { parseRoute, routeHash } from "./state";
import { fixtureBundle } from "./test/fixture";
import { isDark, loadThemeChoice, saveThemeChoice } from "./theme";

describe("routing", () => {
  it("parses and rebuilds hashes", () => {
    expect(parseRoute("")).toEqual({ page: "home" });
    expect(parseRoute("#/pv")).toEqual({ page: "pv" });
    expect(parseRoute("#/nope")).toEqual({ page: "home" });
    expect(parseRoute("#/slides/p1/3")).toEqual({ page: "slides", deck: "p1", slide: 3 });
    expect(parseRoute("#/slides/p1/x")).toEqual({ page: "slides", deck: "p1", slide: undefined });
    expect(routeHash({ page: "slides", deck: "p2", slide: 4 })).toBe("#/slides/p2/4");
    expect(routeHash({ page: "home" })).toBe("#/");
    for (const h of ["#/lots", "#/data", "#/lab", "#/slides/seguimiento/2"]) expect(routeHash(parseRoute(h))).toBe(h);
  });
});

describe("labels", () => {
  const b = fixtureBundle();
  it("translates events, attributes and model terms", () => {
    expect(makeLang("es").tr("a", "b")).toBe("a");
    expect(makeLang("en").tr("a", "b")).toBe("b");
    expect(eventLabel(b, "ev_fever_39", "es")).toBe("Fiebre ≥39 °C");
    expect(eventLabel(b, "ev_unknown_thing", "en")).toBe("unknown thing");
    expect(attributeLabel(b, "z_endotoxin", "es")).toBe("Endotoxina");
    expect(termLabel(b, "vac_DPT", "es")).toBe("Vacuna DPT");
    expect(termLabel(b, "region_Oriente", "en")).toBe("Region Oriente");
    expect(termLabel(b, "female", "en")).toBe("Female sex");
  });
});

describe("theme", () => {
  it("classifies surfaces", () => {
    expect(isDark("#1a1a19")).toBe(true);
    expect(isDark("#fcfcfb")).toBe(false);
    expect(isDark("not-a-colour")).toBe(false);
  });

  it("survives blocked storage", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadThemeChoice()).toBe("auto");
    expect(() => saveThemeChoice("dark")).not.toThrow();
    spy.mockRestore();
    set.mockRestore();
  });
});

describe("lab timeline", () => {
  it("collapses repeated steps and sums their row counts", async () => {
    const { groupSteps } = await import("./pages/Lab");
    const g = groupSteps([
      { step: "generate_synthetic" },
      { step: "ingest_aefi_file", rows_out: 10 },
      { step: "ingest_aefi_file", rows_out: 5 },
      { step: "traceback", detail: "x" },
      { step: "build_release", rows_out: 90 },
    ]);
    expect(g).toEqual([
      { step: "generate_synthetic", count: 1, rows: null },
      { step: "ingest_aefi_file", count: 2, rows: 15 },
      { step: "build_release", count: 1, rows: 90 },
    ]);
  });
});
