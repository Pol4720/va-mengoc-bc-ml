// Shared chart chrome: recessive hairline axes, text tokens, tooltip layout (value first, label
// second, line keys) and HTML escaping of every label inserted in tooltips.

import type { Lang } from "../data/format";
import type { Tokens } from "../theme";

export function esc(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export interface TipRow {
  color?: string;
  value: string;
  label: string;
  key?: "line" | "dot" | "rect";
}

/** Tooltip HTML: the value leads in strong ink, the series name follows in secondary ink. */
export function tipHtml(t: Tokens, title: string, rows: TipRow[], foot?: string): string {
  const keyHtml = (r: TipRow) => {
    if (!r.color) return "";
    const shape =
      r.key === "dot"
        ? "width:8px;height:8px;border-radius:50%"
        : r.key === "rect"
          ? "width:10px;height:9px;border-radius:2px"
          : "width:14px;height:2px;border-radius:2px";
    return `<span style="display:inline-block;${shape};background:${r.color};margin-right:6px;vertical-align:middle"></span>`;
  };
  const body = rows
    .map(
      (r) =>
        `<div style="display:flex;align-items:center;gap:2px;margin-top:3px">${keyHtml(r)}` +
        `<strong style="color:${t.ink};font-weight:650;margin-right:6px">${esc(r.value)}</strong>` +
        `<span style="color:${t.ink2}">${esc(r.label)}</span></div>`,
    )
    .join("");
  const footHtml = foot ? `<div style="color:${t.muted};margin-top:5px;font-size:11px">${esc(foot)}</div>` : "";
  return `<div style="font-size:12px;line-height:1.35"><div style="color:${t.ink2};font-weight:600">${esc(title)}</div>${body}${footHtml}</div>`;
}

export function tooltipBase(t: Tokens, trigger: "axis" | "item") {
  return {
    trigger,
    confine: true,
    backgroundColor: t.surface,
    borderColor: t.grid,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: t.ink, fontFamily: t.font, fontSize: 12 },
    extraCssText: "border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.14);",
    axisPointer:
      trigger === "axis"
        ? { type: "line" as const, lineStyle: { color: t.axis, width: 1, type: "solid" as const }, z: 0 }
        : undefined,
  };
}

export function axisStyle(t: Tokens) {
  return {
    axisLine: { show: true, lineStyle: { color: t.axis, width: 1 } },
    axisTick: { show: false },
    axisLabel: { color: t.axisLabel, fontFamily: t.font, fontSize: 11, hideOverlap: true },
    splitLine: { show: false, lineStyle: { color: t.grid, width: 1, type: "solid" as const } },
    nameTextStyle: { color: t.muted, fontFamily: t.font, fontSize: 11, align: "left" as const },
  };
}

export function valueAxisStyle(t: Tokens) {
  const a = axisStyle(t);
  return { ...a, axisLine: { show: false }, splitLine: { ...a.splitLine, show: true } };
}

export function baseOption(t: Tokens) {
  return {
    animation: !t.reducedMotion,
    animationDuration: 700,
    animationEasing: "cubicOut" as const,
    backgroundColor: "transparent",
    textStyle: { fontFamily: t.font, color: t.ink2 },
    color: [t.s1, t.s2, t.s3],
  };
}

/** Number formatter for axes and tooltips in the active language. */
export function numFmt(lang: Lang, digits: number): (v: number) => string {
  const f = new Intl.NumberFormat(lang === "es" ? "es-ES" : "en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return (v: number) => (Number.isFinite(v) ? f.format(v) : "—");
}

/** Axis tick formatter that drops trailing zeros (clean ticks: 0,5 / 1 / 2). */
export function tickFmt(lang: Lang): (v: number) => string {
  const f = new Intl.NumberFormat(lang === "es" ? "es-ES" : "en-GB", { maximumFractionDigits: 2 });
  return (v: number) => f.format(v);
}
