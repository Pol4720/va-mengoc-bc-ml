import { describe, expect, it } from "vitest";
import { FALLBACK_TOKENS as T } from "../theme";
import { esc, tipHtml } from "./base";
import { bars, forest, forestAxis, heatmap, niceStep } from "./builders";

describe("chart helpers", () => {
  it("escapes labels inserted in tooltips", () => {
    expect(esc('<img src=x onerror="alert(1)">')).toBe("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
    const html = tipHtml(T, "<b>t</b>", [{ value: "1", label: "<script>" }]);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("chooses clean steps", () => {
    expect(niceStep(0.13)).toBeCloseTo(0.1);
    expect(niceStep(0.3)).toBeCloseTo(0.2);
    expect(niceStep(4)).toBe(5);
    expect(niceStep(0)).toBe(1);
  });

  it("uses a linear axis for narrow odds-ratio ranges and a log axis for wide ones", () => {
    const narrow = forestAxis([{ cat: 0, est: 1.2, lo: 1.05, hi: 1.4 }], true, [1]);
    expect(narrow.log).toBe(false);
    expect(narrow.min).toBeLessThanOrEqual(1);
    expect(narrow.max).toBeGreaterThanOrEqual(1.4);
    const wide = forestAxis(
      [
        { cat: 0, est: 0.2, lo: 0.05, hi: 0.8 },
        { cat: 1, est: 8, lo: 3, hi: 20 },
      ],
      true,
      [1],
    );
    expect(wide.log).toBe(true);
  });

  it("clips extreme interval ends but keeps every estimate and reference visible", () => {
    const ax = forestAxis(
      [
        { cat: 0, est: 0.5, lo: 0.2, hi: 0.8 },
        { cat: 1, est: -0.5, lo: -12, hi: 2 },
      ],
      false,
      [0],
    );
    expect(ax.min).toBeGreaterThan(-12);
    expect(ax.min).toBeLessThanOrEqual(-0.5);
    expect(ax.max).toBeGreaterThanOrEqual(0.5);
  });

  it("builds options with one series per group and the theme colours", () => {
    const opt = forest(T, "en", {
      categories: ["a", "b"],
      series: [
        { name: "Signal", color: T.s1, points: [{ cat: 0, est: 1.5, lo: 1.1, hi: 2 }] },
        { name: "No signal", color: T.deemph, points: [{ cat: 1, est: 0.9, lo: 0.7, hi: 1.2 }] },
      ],
      log: true,
      ref: 1,
    }) as { series: { name: string }[]; xAxis: { type: string } };
    expect(opt.series.map((s) => s.name)).toEqual(["Signal", "No signal"]);
    expect(opt.xAxis.type).toBe("value");
  });

  it("caps bar thickness and rounds only the data end", () => {
    const opt = bars(T, "es", { categories: ["x"], series: [{ name: "s", color: T.s1, values: [3] }] }) as {
      series: { barMaxWidth: number; data: { itemStyle: { borderRadius: number[] } }[] }[];
    };
    expect(opt.series[0]?.barMaxWidth).toBe(24);
    expect(opt.series[0]?.data[0]?.itemStyle.borderRadius).toEqual([4, 4, 0, 0]);
  });

  it("uses a grey midpoint for diverging heat maps", () => {
    const opt = heatmap(T, "en", { x: ["a"], y: ["b"], cells: [[0, 0, 0.2]], min: -1, max: 1, diverging: true, valueLabel: "r" }) as {
      visualMap: { inRange: { color: string[] } };
    };
    expect(opt.visualMap.inRange.color).toEqual([T.divNeg, T.divMid, T.divPos]);
  });
});
