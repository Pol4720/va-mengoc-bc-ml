// Small UI building blocks: figure card with chart/table toggle and CSV export, stat tile,
// segmented control, legend with mark-shaped keys, and accessible data table.

import { useId, useState, type ReactNode } from "react";
import { useLang } from "../i18n";

export interface Column {
  key: string;
  label: string;
  numeric?: boolean;
}

export interface TableData {
  columns: Column[];
  rows: Record<string, string | number | ReactNode>[];
  /** Plain values for CSV export (defaults to rows when they hold only strings and numbers). */
  csvRows?: Record<string, string | number>[];
}

export function DataTable({ data, caption }: { data: TableData; caption?: string }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={caption}>
      <table className="data">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {data.columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? "num" : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i}>
              {data.columns.map((c) => (
                <td key={c.key} className={c.numeric ? "num" : undefined}>
                  {r[c.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  // Neutralise spreadsheet formulas and quote every field.
  const safe = /^[=+\-@\t\r]/.test(s) && !/^-?\d/.test(s) ? `'${s}` : s;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function toCsv(data: TableData): string {
  const rows = data.csvRows ?? (data.rows as Record<string, string | number>[]);
  const head = data.columns.map((c) => csvCell(c.label)).join(",");
  const body = rows.map((r) => data.columns.map((c) => csvCell(r[c.key])).join(","));
  return [head, ...body].join("\r\n");
}

function download(name: string, text: string) {
  const blob = new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

interface FigureProps {
  title: string;
  subtitle?: string;
  note?: ReactNode;
  legend?: ReactNode;
  table?: TableData;
  csvName?: string;
  children: ReactNode;
  className?: string;
  /** Start in table view (used when the chart relies on a light hue below 3:1 contrast). */
  defaultView?: "chart" | "table";
}

export function Figure({ title, subtitle, note, legend, table, csvName, children, className, defaultView }: FigureProps) {
  const { tr } = useLang();
  const [view, setView] = useState<"chart" | "table">(defaultView ?? "chart");
  const id = useId();
  return (
    <section className={className ? `card ${className}` : "card"} aria-labelledby={id}>
      <div className="card-head">
        <div>
          <h3 id={id}>{title}</h3>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {table ? (
          <div className="card-actions no-print">
            <Segmented
              label={tr("Vista", "View")}
              value={view}
              onChange={(v) => setView(v as "chart" | "table")}
              options={[
                { value: "chart", label: tr("Gráfico", "Chart") },
                { value: "table", label: tr("Tabla", "Table") },
              ]}
            />
            {csvName ? (
              <button
                type="button"
                className="btn small"
                onClick={() => download(`${csvName}.csv`, toCsv(table))}
                aria-label={tr(`Descargar CSV: ${title}`, `Download CSV: ${title}`)}
                title="CSV"
              >
                <DownloadIcon />
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {view === "chart" || !table ? (
        <>
          {legend}
          {children}
        </>
      ) : (
        <DataTable data={table} caption={title} />
      )}
      {note ? <p className="card-note">{note}</p> : null}
    </section>
  );
}

export function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 2v8m0 0 3-3m-3 3L5 7M3 13h10" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  );
}

interface SegmentedProps {
  label: string;
  value: string;
  options: { value: string; label: string; title?: string }[];
  onChange: (v: string) => void;
}

export function Segmented({ label, value, options, onChange }: SegmentedProps) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          title={o.title}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export interface LegendItem {
  label: string;
  color: string;
  shape?: "line" | "dot" | "rect" | "band" | "dashed";
}

export function Legend({ items }: { items: LegendItem[] }) {
  return (
    <div className="legend" aria-hidden="true">
      {items.map((it) => (
        <span key={it.label}>
          {it.shape === "dashed" ? (
            <span className="key-line" style={{ background: `repeating-linear-gradient(90deg, ${it.color} 0 4px, transparent 4px 7px)` }} />
          ) : (
            <span
              className={it.shape === "dot" ? "key-dot" : it.shape === "rect" ? "key-rect" : it.shape === "band" ? "key-band" : "key-line"}
              style={{ background: it.color }}
            />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

export function SectionTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      {sub ? <p>{sub}</p> : null}
    </div>
  );
}

export function Badge({ kind, children }: { kind?: "on" | "warn" | "bad" | "ok"; children: ReactNode }) {
  return <span className={kind ? `badge ${kind}` : "badge"}>{children}</span>;
}
