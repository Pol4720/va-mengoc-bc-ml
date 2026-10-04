// Smoke test: the whole app renders every page and deck in both languages with the release
// bundle copied by `npm run data` (synthetic unless a public release exists), without runtime errors.

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import raw from "../../public/data/bundle.json?raw";
import { App } from "../App";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

let root: Root;
let host: HTMLDivElement;
const errors: unknown[] = [];

async function go(hash: string) {
  await act(async () => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await new Promise((r) => setTimeout(r, 0));
  });
  // lazily loaded pages: wait until the loading indicator has gone
  for (let i = 0; i < 200 && host.querySelector('[role="status"]'); i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
}

beforeAll(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.spyOn(console, "error").mockImplementation((...args) => errors.push(args));
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(raw, { status: 200, headers: { "Content-Type": "application/json" } })),
  );
  window.localStorage.setItem("vamengoc.lang", "es");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<App />);
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
});

afterAll(() => {
  act(() => root.unmount());
  vi.unstubAllGlobals();
});

const PAGES: [string, string, string][] = [
  ["#/", "Del registro a la evidencia", "From records to evidence"],
  ["#/pv", "Seguridad poscomercialización", "Post-marketing safety"],
  ["#/lots", "Atributos de liberación de lotes", "Lot release attributes"],
  ["#/data", "Calidad de datos y contexto", "Data quality and context"],
  ["#/lab", "Laboratorio de análisis", "Analysis lab"],
  ["#/slides", "Presentaciones para las reuniones", "Decks for the expert meetings"],
];

describe("app smoke test", () => {
  it("shows the synthetic-data warning", async () => {
    await go("#/");
    expect(host.textContent).toContain("Datos sintéticos");
  });

  for (const [hash, es, en] of PAGES) {
    it(`renders ${hash} in Spanish and English`, async () => {
      await go(hash);
      expect(host.querySelector("h1")?.textContent).toContain(es);
      const enBtn = [...host.querySelectorAll<HTMLButtonElement>(".toolbar .seg button")].find((b) => b.textContent === "EN");
      await act(async () => enBtn?.click());
      expect(host.querySelector("h1")?.textContent).toContain(en);
      const esBtn = [...host.querySelectorAll<HTMLButtonElement>(".toolbar .seg button")].find((b) => b.textContent === "ES");
      await act(async () => esBtn?.click());
    });
  }

  it("renders every slide of every deck", async () => {
    for (const [deck, n] of [
      ["seguimiento", 7],
      ["p1", 8],
      ["p2", 7],
    ] as const) {
      for (let i = 1; i <= n; i++) {
        await go(`#/slides/${deck}/${i}`);
        expect(host.querySelector(".slide h2")?.textContent?.length).toBeGreaterThan(0);
        expect(host.querySelector(".slide-foot")?.textContent).toContain(`${i} / ${n}`);
      }
    }
  });

  it("re-thresholds signals when the rule changes", async () => {
    await go("#/pv");
    const tile = () =>
      [...host.querySelectorAll(".stat")].find((s) => s.textContent?.includes("Señales con la regla elegida"))?.querySelector(".value")
        ?.textContent;
    const before = tile();
    const btn = [...host.querySelectorAll<HTMLButtonElement>(".filters .seg button")].find((b) => b.textContent === "≥2");
    await act(async () => btn?.click());
    expect(btn?.getAttribute("aria-pressed")).toBe("true");
    expect(tile()).toMatch(/^\d+$/);
    expect(before).toMatch(/^\d+$/);
  });

  it("switches between chart and table views", async () => {
    await go("#/pv");
    const tableBtn = [...host.querySelectorAll<HTMLButtonElement>(".card-actions .seg button")].find((b) => b.textContent === "Tabla");
    await act(async () => tableBtn?.click());
    expect(host.querySelector("table.data")).not.toBeNull();
  });

  it("logged no React errors", () => {
    expect(errors).toEqual([]);
  });
});
