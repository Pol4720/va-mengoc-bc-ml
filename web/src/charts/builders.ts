// Chart option builders. Each takes plain arrays (already filtered by the page) plus the theme
// tokens and language, and returns a complete ECharts option. Mark specs follow the dataviz
// system: 2px lines, >=8px markers with a surface ring, bars <=24px with 4px rounded data ends,
// hairline solid grid, one value axis, legend for two or more series.

import type { Lang } from "../data/format";
import type { Tokens } from "../theme";
import { axisStyle, baseOption, esc, numFmt, tickFmt, tipHtml, tooltipBase, valueAxisStyle, type TipRow } from "./base";
import type { EChartsOption } from "./echarts";

const finite = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);
const orNull = (v: number | null | undefined): number | null => (finite(v) ? v : null);

interface TipParam {
  dataIndex: number;
  seriesIndex?: number;
  data?: unknown;
}

function firstIndex(p: unknown): number {
  const arr = (Array.isArray(p) ? p : [p]) as TipParam[];
  return arr[0]?.dataIndex ?? 0;
}

export interface RefLine {
  value: number;
  label: string;
  axis?: "x" | "y";
}

function markLines(t: Tokens, refs: RefLine[] | undefined, axis: "x" | "y") {
  if (!refs?.length) return undefined;
  return {
    silent: true,
    symbol: "none",
    animation: false,
    lineStyle: { color: t.muted, width: 1, type: "dashed" as const },
    label: {
      color: t.muted,
      fontSize: 11,
      fontFamily: t.font,
      formatter: (p: { name?: string }) => p.name ?? "",
      position: axis === "y" ? ("insideEndTop" as const) : ("end" as const),
      distance: 4,
    },
    data: refs.map((r) => (axis === "y" ? { yAxis: r.value, name: r.label } : { xAxis: r.value, name: r.label })),
  };
}

// ---- Line with confidence band --------------------------------------------------------------

export interface BandLineInput {
  x: (string | number)[];
  y: (number | null)[];
  lo?: (number | null)[];
  hi?: (number | null)[];
  name: string;
  yName?: string;
  digits?: number;
  refs?: RefLine[];
  bandLabel?: string;
  yMin?: number;
  yMax?: number;
}

export function bandLine(t: Tokens, lang: Lang, d: BandLineInput): EChartsOption {
  const f = numFmt(lang, d.digits ?? 1);
  const last = d.y.reduce<number>((acc, v, i) => (finite(v) ? i : acc), -1);
  const series: unknown[] = [];
  if (d.lo && d.hi) {
    const lo = d.lo;
    series.push(
      {
        type: "line",
        data: lo.map(orNull),
        stack: "band",
        symbol: "none",
        lineStyle: { opacity: 0 },
        silent: true,
        tooltip: { show: false },
      },
      {
        type: "line",
        data: d.hi.map((h, i) => {
          const l = lo[i];
          return finite(h) && finite(l) ? h - l : null;
        }),
        stack: "band",
        symbol: "none",
        lineStyle: { opacity: 0 },
        areaStyle: { color: t.band, opacity: 1 },
        silent: true,
        tooltip: { show: false },
      },
    );
  }
  series.push({
    type: "line",
    name: d.name,
    data: d.y.map(orNull),
    symbol: "circle",
    symbolSize: 8,
    connectNulls: false,
    itemStyle: { color: t.s1, borderColor: t.surface, borderWidth: 2 },
    lineStyle: { width: 2, color: t.s1, cap: "round", join: "round" },
    emphasis: { scale: 1.4 },
    label: {
      show: true,
      position: "top",
      color: t.ink2,
      fontSize: 11,
      formatter: (p: { dataIndex: number; value: unknown }) => (p.dataIndex === last ? f(Number(p.value)) : ""),
    },
    markLine: markLines(t, d.refs, "y"),
    z: 3,
  });
  return {
    ...baseOption(t),
    grid: { left: 8, right: 24, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      ...tooltipBase(t, "axis"),
      formatter: (p: unknown) => {
        const i = firstIndex(p);
        const rows: TipRow[] = [{ color: t.s1, value: f(Number(d.y[i])), label: d.name }];
        const lo = d.lo?.[i];
        const hi = d.hi?.[i];
        if (finite(lo) && finite(hi)) rows.push({ value: `${f(lo)}–${f(hi)}`, label: d.bandLabel ?? "IC 95 %" });
        return tipHtml(t, String(d.x[i]), rows);
      },
    },
    xAxis: { type: "category", data: d.x.map(String), boundaryGap: false, ...axisStyle(t) },
    yAxis: {
      type: "value",
      name: d.yName,
      nameLocation: "end",
      min: d.yMin,
      max: d.yMax,
      ...valueAxisStyle(t),
      axisLabel: { ...valueAxisStyle(t).axisLabel, formatter: tickFmt(lang) },
    },
    series,
  } as EChartsOption;
}

// ---- Forest plot (dot + whisker), one or more series ------------------------------------------

export interface ForestPoint {
  cat: number;
  est: number;
  lo: number;
  hi: number;
  tip?: string[];
}

export interface ForestSeries {
  name: string;
  color: string;
  points: ForestPoint[];
}

export interface ForestInput {
  categories: string[];
  series: ForestSeries[];
  log?: boolean;
  ref?: number;
  refLabel?: string;
  xName?: string;
  digits?: number;
  extraRefs?: RefLine[];
  band?: { from: number; to: number; label: string };
}

interface RenderApi {
  value: (i: number) => number;
  coord: (v: number[]) => number[];
}

/** Step of 1, 2 or 5 times a power of ten close to x (for clean axis bounds). */
export function niceStep(x: number): number {
  if (!(x > 0) || !Number.isFinite(x)) return 1;
  const p = 10 ** Math.floor(Math.log10(x));
  const m = x / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

export interface AxisBounds {
  log: boolean;
  min: number;
  max: number;
}

/**
 * Axis for a forest plot: a log scale only when the plotted range spans at least a factor of 4
 * (otherwise a linear scale reads better); bounds cover every estimate, the references and the
 * band, and clip extreme interval ends at 0.75 times the spread of the estimates.
 */
export function forestAxis(points: ForestPoint[], wantLog: boolean, extra: number[] = []): AxisBounds {
  const pos = (v: number) => !wantLog || v > 0;
  const est = points.map((p) => p.est).filter((v) => finite(v) && pos(v));
  if (!est.length) return { log: false, min: 0, max: 1 };
  const lo = points.map((p) => p.lo).filter((v) => finite(v) && pos(v));
  const hi = points.map((p) => p.hi).filter((v) => finite(v) && pos(v));
  const ex = extra.filter((v) => finite(v) && pos(v));
  const tf = wantLog ? Math.log10 : (v: number) => v;
  const inv = wantLog ? (v: number) => 10 ** v : (v: number) => v;
  const eMin = Math.min(...est.map(tf));
  const eMax = Math.max(...est.map(tf));
  const spread = Math.max(eMax - eMin, wantLog ? 0.1 : 0.2);
  let min = Math.max(Math.min(eMin, ...lo.map(tf)), eMin - 0.75 * spread);
  let max = Math.min(Math.max(eMax, ...hi.map(tf)), eMax + 0.75 * spread);
  min = Math.min(min, ...ex.map(tf));
  max = Math.max(max, ...ex.map(tf));
  const pad = 0.04 * (max - min || 1);
  min -= pad;
  max += pad;
  if (wantLog && max - min < Math.log10(4)) {
    return forestAxis(points, false, extra);
  }
  if (wantLog) {
    const step = 0.1;
    return { log: true, min: inv(Math.floor(min / step) * step), max: inv(Math.ceil(max / step) * step) };
  }
  const step = niceStep((max - min) / 5);
  return { log: false, min: Math.floor(min / step) * step, max: Math.ceil(max / step) * step };
}

export function forest(t: Tokens, lang: Lang, d: ForestInput): EChartsOption {
  const f = numFmt(lang, d.digits ?? 2);
  const n = d.series.length;
  const axis = forestAxis(
    d.series.flatMap((s) => s.points),
    !!d.log,
    [
      ...(d.ref !== undefined ? [d.ref] : []),
      ...(d.extraRefs ?? []).map((r) => r.value),
      ...(d.band ? [d.band.from, d.band.to] : []),
    ],
  );
  const ok = (p: ForestPoint) => finite(p.est) && (!axis.log || p.est > 0);
  const series = d.series.map((s, si) => {
    const dy = (si - (n - 1) / 2) * 9;
    const pts = s.points.filter(ok);
    return {
      type: "custom",
      name: s.name,
      clip: true,
      encode: { x: [0, 2, 3], y: 1 },
      data: pts.map((p) => [
        p.est,
        p.cat,
        Math.max(finite(p.lo) && (!axis.log || p.lo > 0) ? p.lo : p.est, axis.min),
        Math.min(finite(p.hi) ? p.hi : p.est, axis.max),
      ]),
      itemStyle: { color: s.color },
      renderItem: (_params: unknown, api: RenderApi) => {
        const est = api.value(0);
        const cat = api.value(1);
        const lo = api.value(2);
        const hi = api.value(3);
        const c = api.coord([est, cat]);
        const a = api.coord([lo, cat]);
        const b = api.coord([hi, cat]);
        const y = (c[1] ?? 0) + dy;
        return {
          type: "group",
          children: [
            // transparent hit area larger than the mark
            {
              type: "rect",
              shape: { x: (a[0] ?? 0) - 6, y: y - 10, width: (b[0] ?? 0) - (a[0] ?? 0) + 12, height: 20 },
              style: { fill: "transparent" },
            },
            {
              type: "line",
              shape: { x1: a[0], y1: y, x2: b[0], y2: y },
              style: { stroke: s.color, lineWidth: 2, lineCap: "round" },
            },
            {
              type: "circle",
              shape: { cx: c[0], cy: y, r: 5 },
              style: { fill: s.color, stroke: t.surface, lineWidth: 2 },
            },
          ],
        };
      },
      tooltip: {
        formatter: (p: { dataIndex: number }) => {
          const pt = pts[p.dataIndex];
          if (!pt) return "";
          const rows: TipRow[] = [
            { color: s.color, key: "dot", value: `${f(pt.est)} (${f(pt.lo)}–${f(pt.hi)})`, label: s.name },
          ];
          return tipHtml(t, d.categories[pt.cat] ?? "", rows, pt.tip?.join(" · "));
        },
      },
      z: 3,
    };
  });
  const refs: RefLine[] = [];
  if (d.ref !== undefined) refs.push({ value: d.ref, label: d.refLabel ?? "" });
  refs.push(...(d.extraRefs ?? []));
  if (series[0]) {
    (series[0] as Record<string, unknown>).markLine = {
      ...markLines(t, refs, "x"),
      lineStyle: { color: t.axis, width: 1, type: "solid" },
      // the category axis is inverted, so "start" is the top of the plot
      label: { ...markLines(t, refs, "x")?.label, position: "start", distance: 4 },
      data: refs.map((r, i) => ({
        xAxis: r.value,
        name: r.label,
        lineStyle: i === 0 ? { color: t.axis, type: "solid" } : { color: t.muted, type: "dashed" },
      })),
    };
    if (d.band) {
      (series[0] as Record<string, unknown>).markArea = {
        silent: true,
        itemStyle: { color: t.band },
        label: { show: false },
        data: [[{ xAxis: d.band.from, name: d.band.label }, { xAxis: d.band.to }]],
      };
    }
  }
  return {
    ...baseOption(t),
    grid: { left: 8, right: 28, top: 26, bottom: 8, containLabel: true },
    tooltip: tooltipBase(t, "item"),
    xAxis: {
      type: axis.log ? "log" : "value",
      name: d.xName,
      nameLocation: "middle",
      nameGap: 26,
      min: axis.min,
      max: axis.max,
      ...valueAxisStyle(t),
      nameTextStyle: { ...valueAxisStyle(t).nameTextStyle, align: "center" },
      axisLabel: { ...valueAxisStyle(t).axisLabel, formatter: tickFmt(lang), showMinLabel: !axis.log, showMaxLabel: !axis.log },
    },
    yAxis: {
      type: "category",
      data: d.categories,
      inverse: true,
      ...axisStyle(t),
      axisLine: { show: false },
      axisLabel: { ...axisStyle(t).axisLabel, color: t.ink2, fontSize: 12, hideOverlap: false },
    },
    series,
  } as EChartsOption;
}

export function forestHeight(categories: number, series = 1): number {
  return Math.max(160, categories * (series > 1 ? 34 : 28) + 70);
}

// ---- Bars -------------------------------------------------------------------------------------

export interface BarSeries {
  name: string;
  color: string;
  values: (number | null)[];
}

export interface BarsInput {
  categories: string[];
  series: BarSeries[];
  horizontal?: boolean;
  digits?: number;
  valueName?: string;
  suffix?: string;
  /** Per-bar colours for a single series (emphasis: highlight some, de-emphasise the rest). */
  barColors?: string[];
  labelValues?: boolean;
  max?: number;
}

export function bars(t: Tokens, lang: Lang, d: BarsInput): EChartsOption {
  const f = numFmt(lang, d.digits ?? 0);
  const sfx = d.suffix ?? "";
  const radius = d.horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
  const catAxis = {
    type: "category" as const,
    data: d.categories,
    inverse: !!d.horizontal,
    ...axisStyle(t),
    axisLabel: { ...axisStyle(t).axisLabel, color: d.horizontal ? t.ink2 : t.axisLabel, hideOverlap: !d.horizontal },
  };
  const valAxis = {
    type: "value" as const,
    name: d.valueName,
    max: d.max,
    ...valueAxisStyle(t),
    axisLabel: { ...valueAxisStyle(t).axisLabel, formatter: tickFmt(lang) },
  };
  return {
    ...baseOption(t),
    grid: { left: 8, right: d.horizontal ? 48 : 16, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      ...tooltipBase(t, "axis"),
      axisPointer: { type: "shadow", shadowStyle: { color: t.band } },
      formatter: (p: unknown) => {
        const i = firstIndex(p);
        const rows: TipRow[] = d.series.map((s) => ({
          color: d.barColors?.[i] ?? s.color,
          key: "rect",
          value: finite(s.values[i]) ? `${f(s.values[i] as number)}${sfx}` : "—",
          label: s.name,
        }));
        return tipHtml(t, d.categories[i] ?? "", rows);
      },
    },
    xAxis: d.horizontal ? valAxis : catAxis,
    yAxis: d.horizontal ? catAxis : valAxis,
    series: d.series.map((s) => ({
      type: "bar",
      name: s.name,
      data: s.values.map((v, i) => ({
        value: orNull(v),
        itemStyle: { color: d.barColors?.[i] ?? s.color, borderRadius: radius },
      })),
      barMaxWidth: 24,
      barGap: "12%",
      label: {
        show: !!d.labelValues,
        position: d.horizontal ? "right" : "top",
        color: t.ink2,
        fontSize: 11,
        formatter: (p: { value: unknown }) => (finite(Number(p.value)) ? `${f(Number(p.value))}${sfx}` : ""),
      },
      emphasis: { focus: "none", itemStyle: { opacity: 0.85 } },
    })),
  } as EChartsOption;
}

export function barsHeight(categories: number, series = 1): number {
  return Math.max(160, categories * (series > 1 ? 34 : 26) + 60);
}

// ---- Multi-line (time series) -----------------------------------------------------------------

export interface LineSeries {
  name: string;
  color: string;
  values: (number | null)[];
  step?: boolean;
  symbol?: boolean;
  width?: number;
}

export interface LinesInput {
  x: string[];
  series: LineSeries[];
  yName?: string;
  digits?: number;
  refs?: RefLine[];
  xRefs?: RefLine[];
  zoom?: boolean;
  yMin?: number;
  yMax?: number;
}

export function lines(t: Tokens, lang: Lang, d: LinesInput): EChartsOption {
  const f = numFmt(lang, d.digits ?? 0);
  const series = d.series.map((s, i) => ({
    type: "line",
    name: s.name,
    data: s.values.map(orNull),
    step: s.step ? "middle" : undefined,
    symbol: s.symbol ? "circle" : "none",
    symbolSize: 8,
    showSymbol: !!s.symbol,
    itemStyle: { color: s.color, borderColor: t.surface, borderWidth: 2 },
    lineStyle: { width: s.width ?? 2, color: s.color, cap: "round", join: "round" },
    emphasis: { disabled: true },
    markLine: i === 0 ? mergeMarkLines(t, d.refs, d.xRefs) : undefined,
    z: 3 + i,
  }));
  return {
    ...baseOption(t),
    grid: { left: 8, right: 20, top: 28, bottom: d.zoom ? 44 : 8, containLabel: true },
    tooltip: {
      ...tooltipBase(t, "axis"),
      formatter: (p: unknown) => {
        const i = firstIndex(p);
        return tipHtml(
          t,
          d.x[i] ?? "",
          d.series.map((s) => ({
            color: s.color,
            value: finite(s.values[i]) ? f(s.values[i] as number) : "—",
            label: s.name,
          })),
        );
      },
    },
    dataZoom: d.zoom
      ? [
          { type: "inside", throttle: 50 },
          {
            type: "slider",
            height: 18,
            bottom: 8,
            borderColor: t.grid,
            fillerColor: t.band,
            handleStyle: { color: t.surface, borderColor: t.axis },
            moveHandleStyle: { color: t.axis },
            dataBackground: { lineStyle: { color: t.axis }, areaStyle: { color: t.grid } },
            selectedDataBackground: { lineStyle: { color: t.s1 }, areaStyle: { color: t.band } },
            textStyle: { color: t.axisLabel, fontSize: 10 },
          },
        ]
      : undefined,
    xAxis: { type: "category", data: d.x, boundaryGap: false, ...axisStyle(t) },
    yAxis: {
      type: "value",
      name: d.yName,
      min: d.yMin,
      max: d.yMax,
      ...valueAxisStyle(t),
      axisLabel: { ...valueAxisStyle(t).axisLabel, formatter: tickFmt(lang) },
    },
    series,
  } as EChartsOption;
}

function mergeMarkLines(t: Tokens, refs?: RefLine[], xRefs?: RefLine[]) {
  const y = markLines(t, refs, "y");
  const x = markLines(t, xRefs, "x");
  if (!y && !x) return undefined;
  return { ...(y ?? x), data: [...(y?.data ?? []), ...(x?.data ?? [])] };
}

// ---- Quantile fan (q10–q90, q25–q75 bands and median) -----------------------------------------

export interface FanInput {
  x: string[];
  q10: (number | null)[];
  q25: (number | null)[];
  q50: (number | null)[];
  q75: (number | null)[];
  q90: (number | null)[];
  n?: (number | null)[];
  yName?: string;
  labels: { median: string; inner: string; outer: string; n: string };
  refs?: RefLine[];
}

export function fan(t: Tokens, lang: Lang, d: FanInput): EChartsOption {
  const f = numFmt(lang, 2);
  const diff = (a: (number | null)[], b: (number | null)[]) =>
    a.map((v, i) => {
      const w = b[i];
      return finite(v) && finite(w) ? v - w : null;
    });
  const bandSeries = (data: (number | null)[], stack: string, color?: string) => ({
    type: "line",
    data,
    stack,
    symbol: "none",
    lineStyle: { opacity: 0 },
    areaStyle: color ? { color, opacity: 1 } : undefined,
    silent: true,
    tooltip: { show: false },
  });
  return {
    ...baseOption(t),
    grid: { left: 8, right: 20, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      ...tooltipBase(t, "axis"),
      formatter: (p: unknown) => {
        const i = firstIndex(p);
        const q = (a: (number | null)[]) => (finite(a[i]) ? f(a[i] as number) : "—");
        return tipHtml(
          t,
          d.x[i] ?? "",
          [
            { color: t.s1, value: q(d.q50), label: d.labels.median },
            { color: t.band2, key: "rect", value: `${q(d.q25)}–${q(d.q75)}`, label: d.labels.inner },
            { color: t.band, key: "rect", value: `${q(d.q10)}–${q(d.q90)}`, label: d.labels.outer },
          ],
          d.n && finite(d.n[i]) ? `${d.labels.n}: ${numFmt(lang, 0)(d.n[i] as number)}` : undefined,
        );
      },
    },
    xAxis: { type: "category", data: d.x, boundaryGap: false, ...axisStyle(t) },
    yAxis: {
      type: "value",
      name: d.yName,
      ...valueAxisStyle(t),
      axisLabel: { ...valueAxisStyle(t).axisLabel, formatter: tickFmt(lang) },
    },
    series: [
      bandSeries(d.q10.map(orNull), "outer"),
      bandSeries(diff(d.q90, d.q10), "outer", t.band),
      bandSeries(d.q25.map(orNull), "inner"),
      bandSeries(diff(d.q75, d.q25), "inner", t.band2),
      {
        type: "line",
        name: d.labels.median,
        data: d.q50.map(orNull),
        symbol: "circle",
        symbolSize: 8,
        itemStyle: { color: t.s1, borderColor: t.surface, borderWidth: 2 },
        lineStyle: { width: 2, color: t.s1 },
        markLine: markLines(t, d.refs, "y"),
        z: 3,
      },
    ],
  } as EChartsOption;
}

// ---- Heatmap (sequential or diverging) --------------------------------------------------------

export interface HeatInput {
  x: string[];
  y: string[];
  cells: [number, number, number | null][];
  min: number;
  max: number;
  diverging?: boolean;
  digits?: number;
  valueLabel: string;
  showLabels?: boolean;
}

export function heatmap(t: Tokens, lang: Lang, d: HeatInput): EChartsOption {
  const f = numFmt(lang, d.digits ?? 2);
  const colors = d.diverging ? [t.divNeg, t.divMid, t.divPos] : [t.seq[0], t.seq[2], t.seq[4]];
  return {
    ...baseOption(t),
    grid: { left: 8, right: 16, top: 8, bottom: 56, containLabel: true },
    tooltip: {
      ...tooltipBase(t, "item"),
      formatter: (p: unknown) => {
        const v = (p as { value: [number, number, number | null] }).value;
        const val = finite(v[2]) ? f(v[2]) : "—";
        return tipHtml(t, `${d.y[v[1]] ?? ""} × ${d.x[v[0]] ?? ""}`, [{ value: val, label: d.valueLabel }]);
      },
    },
    xAxis: {
      type: "category",
      data: d.x,
      ...axisStyle(t),
      axisLine: { show: false },
      axisLabel: { ...axisStyle(t).axisLabel, rotate: d.x.length > 8 ? 35 : 0, hideOverlap: false, interval: 0 },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: d.y,
      inverse: true,
      ...axisStyle(t),
      axisLine: { show: false },
      axisLabel: { ...axisStyle(t).axisLabel, color: t.ink2, hideOverlap: false, interval: 0 },
    },
    visualMap: {
      min: d.min,
      max: d.max,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 12,
      itemHeight: 160,
      inRange: { color: colors },
      text: [f(d.max), f(d.min)],
      textGap: 6,
      textStyle: { color: t.axisLabel, fontSize: 11 },
    },
    series: [
      {
        type: "heatmap",
        data: d.cells.map(([x, y, v]) => [x, y, orNull(v)]),
        itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 3 },
        label: {
          show: !!d.showLabels,
          fontSize: 10,
          color: t.ink,
          textBorderColor: t.surface,
          textBorderWidth: 2,
          formatter: (p: { value: [number, number, number | null] }) =>
            finite(p.value[2]) ? numFmt(lang, 1)(p.value[2]) : "",
        },
        emphasis: { itemStyle: { borderColor: t.ink, borderWidth: 1 } },
      },
    ],
  } as EChartsOption;
}

// ---- Control chart (individual values on the z scale, run-rule flags) -------------------------

export interface ControlInput {
  seq: number[];
  values: (number | null)[];
  flagged: boolean[];
  years: (number | null)[];
  name: string;
  flaggedName: string;
  yName: string;
  limits?: { value: number; label: string }[];
  center?: { value: number; label: string };
  ucl?: (number | null)[];
  lcl?: (number | null)[];
  limitName?: string;
  digits?: number;
  zoomStartPct?: number;
  yearLabel: string;
  lotLabel: string;
}

export function controlChart(t: Tokens, lang: Lang, d: ControlInput): EChartsOption {
  const f = numFmt(lang, d.digits ?? 2);
  const x = d.seq.map(String);
  const flaggedData = d.values.map((v, i) => (d.flagged[i] && finite(v) ? v : null));
  const series: unknown[] = [
    {
      type: "line",
      name: d.name,
      data: d.values.map(orNull),
      symbol: "none",
      lineStyle: { width: 2, color: t.s1, join: "round" },
      itemStyle: { color: t.s1 },
      emphasis: { disabled: true },
      markLine: markLines(
        t,
        [...(d.limits ?? []), ...(d.center ? [d.center] : [])].map((l) => ({ ...l, axis: "y" as const })),
        "y",
      ),
      z: 2,
    },
    {
      type: "scatter",
      name: d.flaggedName,
      data: flaggedData,
      symbol: "diamond",
      symbolSize: 11,
      itemStyle: { color: t.critical, borderColor: t.surface, borderWidth: 2 },
      z: 4,
    },
  ];
  if (d.ucl && d.lcl) {
    for (const [arr] of [[d.ucl], [d.lcl]] as const) {
      series.push({
        type: "line",
        name: d.limitName,
        data: arr.map(orNull),
        symbol: "none",
        lineStyle: { width: 1, color: t.muted, type: "dashed" },
        itemStyle: { color: t.muted },
        emphasis: { disabled: true },
        z: 1,
      });
    }
  }
  return {
    ...baseOption(t),
    animation: false,
    grid: { left: 8, right: 56, top: 24, bottom: 46, containLabel: true },
    tooltip: {
      ...tooltipBase(t, "axis"),
      formatter: (p: unknown) => {
        const i = firstIndex(p);
        const rows: TipRow[] = [{ color: t.s1, value: finite(d.values[i]) ? f(d.values[i] as number) : "—", label: d.name }];
        if (d.ucl && d.lcl && finite(d.ucl[i]) && finite(d.lcl[i]))
          rows.push({ color: t.muted, value: `${f(d.lcl[i] as number)}–${f(d.ucl[i] as number)}`, label: d.limitName ?? "" });
        if (d.flagged[i]) rows.push({ color: t.critical, key: "dot", value: "◆", label: d.flaggedName });
        return tipHtml(t, `${d.lotLabel} ${x[i]} · ${d.yearLabel} ${d.years[i] ?? "—"}`, rows);
      },
    },
    dataZoom: [
      { type: "inside", start: d.zoomStartPct ?? 70, end: 100, throttle: 50 },
      {
        type: "slider",
        start: d.zoomStartPct ?? 70,
        end: 100,
        height: 18,
        bottom: 8,
        borderColor: t.grid,
        fillerColor: t.band,
        handleStyle: { color: t.surface, borderColor: t.axis },
        moveHandleStyle: { color: t.axis },
        dataBackground: { lineStyle: { color: t.axis }, areaStyle: { color: t.grid } },
        selectedDataBackground: { lineStyle: { color: t.s1 }, areaStyle: { color: t.band } },
        textStyle: { color: t.axisLabel, fontSize: 10 },
      },
    ],
    xAxis: { type: "category", data: x, boundaryGap: false, ...axisStyle(t) },
    yAxis: {
      type: "value",
      name: d.yName,
      scale: true,
      ...valueAxisStyle(t),
      axisLabel: { ...valueAxisStyle(t).axisLabel, formatter: tickFmt(lang) },
    },
    series,
  } as EChartsOption;
}

// ---- Observed points with a fitted curve -------------------------------------------------------

export interface FitInput {
  x: string[];
  observed: (number | null)[];
  fitted: (number | null)[];
  observedName: string;
  fittedName: string;
  yName?: string;
  xRefs?: RefLine[];
  digits?: number;
}

export function observedFitted(t: Tokens, lang: Lang, d: FitInput): EChartsOption {
  const f = numFmt(lang, d.digits ?? 0);
  return {
    ...baseOption(t),
    grid: { left: 8, right: 20, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      ...tooltipBase(t, "axis"),
      formatter: (p: unknown) => {
        const i = firstIndex(p);
        return tipHtml(t, d.x[i] ?? "", [
          { color: t.s1, key: "dot", value: finite(d.observed[i]) ? f(d.observed[i] as number) : "—", label: d.observedName },
          { color: t.s2, value: finite(d.fitted[i]) ? f(d.fitted[i] as number) : "—", label: d.fittedName },
        ]);
      },
    },
    xAxis: { type: "category", data: d.x, boundaryGap: false, ...axisStyle(t) },
    yAxis: {
      type: "value",
      name: d.yName,
      ...valueAxisStyle(t),
      axisLabel: { ...valueAxisStyle(t).axisLabel, formatter: tickFmt(lang) },
    },
    series: [
      {
        type: "scatter",
        name: d.observedName,
        data: d.observed.map(orNull),
        symbolSize: 8,
        itemStyle: { color: t.s1, borderColor: t.surface, borderWidth: 2 },
        z: 3,
      },
      {
        type: "line",
        name: d.fittedName,
        data: d.fitted.map(orNull),
        symbol: "none",
        lineStyle: { width: 2, color: t.s2 },
        itemStyle: { color: t.s2 },
        markLine: markLines(t, d.xRefs, "x"),
        z: 2,
      },
    ],
  } as EChartsOption;
}

export { esc };
