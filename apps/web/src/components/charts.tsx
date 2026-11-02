"use client";

import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatDate, formatNumber, formatPercent } from "@/lib/format";

export interface ChartPoint {
  date: string;
  actual?: number | null;
  forecast: number | null;
  baseline?: number | null;
  band?: [number, number] | null;
}

// Axis ticks are text, so they use the faint-ink token: 5.13:1 on white (AA normal text).
const AXIS = { stroke: "#5c7082", fontSize: 11 };
const GRID = "#e6ecf3";

const numberFormatter = (value: number) => formatNumber(value, 0);

export function ForecastChart({ data, showBaseline }: { data: ChartPoint[]; showBaseline: boolean }) {
  if (data.length === 0) {
    return <p style={{ color: "var(--ink-muted)", fontSize: "0.85rem" }}>No points to plot for this selection.</p>;
  }

  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            stroke={AXIS.stroke}
            fontSize={AXIS.fontSize}
            tickFormatter={(value: string) => formatDate(value).slice(0, 6)}
            minTickGap={24}
          />
          <YAxis stroke={AXIS.stroke} fontSize={AXIS.fontSize} tickFormatter={numberFormatter} width={48} />
          <Tooltip
            contentStyle={{ borderRadius: 8, border: "1px solid #dde5ee", fontSize: 12 }}
            labelFormatter={(value) => formatDate(String(value))}
            formatter={(value: unknown, name: string) => {
              if (Array.isArray(value)) {
                const [low, high] = value as [number, number];
                return [`${formatNumber(low)} – ${formatNumber(high)}`, "Empirical band"] as [string, string];
              }
              return [formatNumber(typeof value === "number" ? value : Number(value)), name] as [string, string];
            }}
          />
          {data.some((point) => point.band) ? (
            <Area
              type="monotone"
              dataKey="band"
              stroke="none"
              fill="#009e73"
              fillOpacity={0.14}
              name="Empirical band"
              isAnimationActive={false}
            />
          ) : null}
          {data.some((point) => point.actual !== null && point.actual !== undefined) ? (
            <Line
              type="monotone"
              dataKey="actual"
              name="Actual"
              stroke="#0072b2"
              strokeWidth={2.4}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ) : null}
          <Line
            type="monotone"
            dataKey="forecast"
            name="Forecast"
            stroke="#009e73"
            strokeWidth={2.4}
            strokeDasharray="6 3"
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          {showBaseline && data.some((point) => point.baseline !== null && point.baseline !== undefined) ? (
            <Line
              type="monotone"
              dataKey="baseline"
              name="Seasonal-naive baseline"
              stroke="#e69f00"
              strokeWidth={2}
              strokeDasharray="2 4"
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ) : null}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ChartLegend({ showBaseline }: { showBaseline: boolean }) {
  return (
    <div className="chart-legend" aria-hidden="true">
      <span className="legend-item">
        <span className="legend-swatch" style={{ background: "#0072b2" }} /> Actual
      </span>
      <span className="legend-item">
        <span className="legend-swatch dashed" style={{ background: "none" }} /> Forecast (dashed teal)
      </span>
      {showBaseline ? (
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: "#e69f00" }} /> Seasonal-naive baseline
        </span>
      ) : null}
      <span className="legend-item">
        <span className="legend-swatch" style={{ background: "rgba(0,158,115,0.25)" }} /> Empirical 10–90% residual band
      </span>
    </div>
  );
}

export function ResidualChart({ bins }: { bins: { lower: number; upper: number; count: number }[] }) {
  const data = bins.map((bin) => ({ label: `${Math.round(bin.lower)}…${Math.round(bin.upper)}`, count: bin.count, mid: (bin.lower + bin.upper) / 2 }));
  return (
    <div className="chart-frame" style={{ minHeight: 200 }}>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke={AXIS.stroke} fontSize={10} interval={1} angle={-20} textAnchor="end" height={44} />
          <YAxis stroke={AXIS.stroke} fontSize={AXIS.fontSize} width={36} allowDecimals={false} />
          <Tooltip
            contentStyle={{ borderRadius: 8, border: "1px solid #dde5ee", fontSize: 12 }}
            formatter={(value: number) => [`${value} series-days`, "Count"]}
            labelFormatter={(label) => `Residual ${label}`}
          />
          <Bar dataKey="count" fill="#d55e00" radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function WapeBars({
  rows,
}: {
  rows: { model_key: string; label: string; wape: number | null; is_selected: boolean }[];
}) {
  const data = rows.map((row) => ({
    name: row.model_key === "seasonal_naive" ? "Seasonal naive" : "Gradient boosting",
    wape: row.wape === null ? 0 : Number((row.wape * 100).toFixed(2)),
    label: row.label,
  }));

  return (
    <div style={{ height: 170 }}>
      <ResponsiveContainer width="100%" height={170}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 32, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" stroke={AXIS.stroke} fontSize={11} unit="%" />
          <YAxis type="category" dataKey="name" stroke={AXIS.stroke} fontSize={11} width={130} />
          <Tooltip
            contentStyle={{ borderRadius: 8, border: "1px solid #dde5ee", fontSize: 12 }}
            formatter={(value: number) => [`WAPE ${value}%`, ""]}
          />
          <Bar dataKey="wape" fill="#1a76c9" radius={[0, 4, 4, 0]} isAnimationActive={false} barSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function compareSummary(rows: { model_key: string; wape: number | null }[]): string {
  const model = rows.find((row) => row.model_key === "hist_gradient_boosting");
  const baseline = rows.find((row) => row.model_key === "seasonal_naive");
  if (!model || !baseline || model.wape === null || baseline.wape === null) {
    return "WAPE is undefined for at least one model on this window (all-zero demand in the holdout).";
  }
  const delta = (baseline.wape - model.wape) / baseline.wape;
  if (delta >= 0) {
    return `The model's holdout WAPE is ${formatPercent(model.wape)} versus ${formatPercent(
      baseline.wape,
    )} for the seasonal-naive baseline — ${formatPercent(delta)} lower error on this window.`;
  }
  return `The model's holdout WAPE is ${formatPercent(model.wape)} versus ${formatPercent(
    baseline.wape,
  )} for the baseline — the model is ${formatPercent(-delta)} worse, so treat these forecasts with caution.`;
}
