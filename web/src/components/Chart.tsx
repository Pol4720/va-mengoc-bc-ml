// ECharts wrapper: SVG renderer (crisp in both themes and in print), resize-aware, disposed on
// unmount, and re-rendered whenever the option (which already embeds the theme tokens) changes.

import { useEffect, useRef } from "react";
import { echarts, type EChartsOption } from "../charts/echarts";

interface ChartProps {
  option: EChartsOption;
  height?: number | string;
  label: string;
  className?: string;
}

export function Chart({ option, height = 320, label, className }: ChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<ReturnType<typeof echarts.init> | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const chart = echarts.init(el, undefined, { renderer: "svg" });
    inst.current = chart;
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => chart.resize()) : null;
    ro?.observe(el);
    return () => {
      ro?.disconnect();
      chart.dispose();
      inst.current = null;
    };
  }, []);

  useEffect(() => {
    inst.current?.setOption(option, { notMerge: true, lazyUpdate: false });
  }, [option]);

  return (
    <div
      ref={ref}
      className={className ? `chart ${className}` : "chart"}
      style={{ height }}
      role="img"
      aria-label={label}
    />
  );
}
