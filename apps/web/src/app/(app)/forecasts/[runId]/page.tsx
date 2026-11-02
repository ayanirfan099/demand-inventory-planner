"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ChartLegend, ForecastChart, ResidualChart, compareSummary, type ChartPoint } from "@/components/charts";
import {
  Badge,
  Card,
  Definition,
  EmptyState,
  ErrorState,
  Loading,
  Notice,
  PageHead,
  SmallCaps,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import {
  HORIZON_NOTICE,
  METRIC_DEFINITIONS,
  formatDate,
  formatNumber,
  formatPercent,
  relativeToBaseline,
} from "@/lib/format";
import type { ComparisonRow, Point, PointsResponse, ResidualsResponse, RunDetailResponse } from "@/lib/types";

type ViewMode = "holdout" | "forward";

export default function RunDetailPage() {
  const params = useParams<{ runId: string }>();
  const runId = Number(params.runId);

  const detail = useApi<RunDetailResponse>(`/api/v1/forecast-runs/${runId}`);
  const comparison = useApi<{ rows: ComparisonRow[]; baseline_run_id: number | null; selection_rule: string }>(
    `/api/v1/forecast-runs/${runId}/comparison`,
  );
  const holdout = useApi<PointsResponse>(`/api/v1/forecast-runs/${runId}/points?kind=holdout&limit=50000`);
  const forward = useApi<PointsResponse>(`/api/v1/forecast-runs/${runId}/points?kind=forecast&limit=50000`);
  const residuals = useApi<ResidualsResponse>(`/api/v1/forecast-runs/${runId}/residuals`);

  const baselineRunId = comparison.data?.baseline_run_id ?? null;
  const baselinePoints = useApi<PointsResponse>(
    baselineRunId ? `/api/v1/forecast-runs/${baselineRunId}/points?kind=holdout&limit=50000` : null,
  );

  const [view, setView] = useState<ViewMode>("holdout");
  const [store, setStore] = useState("all");
  const [item, setItem] = useState("all");
  const [showBaseline, setShowBaseline] = useState(true);

  const series = useMemo(() => detail.data?.series ?? [], [detail.data]);
  const stores = useMemo(() => [...new Set(series.map((row) => row.store))].sort(), [series]);
  const items = useMemo(() => [...new Set(series.map((row) => row.item))].sort(), [series]);

  const chartData = useMemo<ChartPoint[]>(() => {
    const filterPoints = (points: Point[]) =>
      points.filter(
        (point) => (store === "all" || point.store === store) && (item === "all" || point.item === item),
      );

    const merge = (
      primary: Point[],
      baseline: Point[] | null,
      includeBand: boolean,
    ): ChartPoint[] => {
      const byDate = new Map<string, { actual?: number; forecast?: number; baseline?: number; low?: number; high?: number }>();
      for (const point of filterPoints(primary)) {
        const entry = byDate.get(point.date) ?? {};
        entry.forecast = (entry.forecast ?? 0) + point.forecast;
        if (point.actual !== null && point.actual !== undefined) {
          entry.actual = (entry.actual ?? 0) + point.actual;
        }
        if (includeBand) {
          entry.low = (entry.low ?? 0) + (point.lower ?? point.forecast);
          entry.high = (entry.high ?? 0) + (point.upper ?? point.forecast);
        }
        byDate.set(point.date, entry);
      }
      for (const point of filterPoints(baseline ?? [])) {
        const entry = byDate.get(point.date) ?? {};
        entry.baseline = (entry.baseline ?? 0) + point.forecast;
        byDate.set(point.date, entry);
      }
      return [...byDate.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, entry]) => ({
          date,
          actual: entry.actual ?? null,
          forecast: entry.forecast ?? null,
          baseline: entry.baseline ?? null,
          band: includeBand && entry.low !== undefined && entry.high !== undefined ? ([entry.low, entry.high] as [number, number]) : null,
        }));
    };

    if (view === "holdout") {
      return merge(holdout.data?.points ?? [], showBaseline ? baselinePoints.data?.points ?? [] : null, false);
    }
    return merge(forward.data?.points ?? [], null, true);
  }, [view, store, item, showBaseline, holdout.data, forward.data, baselinePoints.data]);

  const chartSummary = useMemo(() => {
    if (chartData.length === 0) return "No points for this selection.";
    const totalForecast = chartData.reduce((sum, point) => sum + (point.forecast ?? 0), 0);
    const totalActual = chartData.reduce((sum, point) => sum + (point.actual ?? 0), 0);
    const scope = store === "all" && item === "all" ? "all selected series" : `${item === "all" ? "all items" : item} @ ${store === "all" ? "all stores" : store}`;
    if (view === "holdout") {
      return `Backtest over ${chartData.length} days for ${scope}: forecast ${formatNumber(totalForecast, 0)} units vs actual ${formatNumber(totalActual, 0)} units (difference ${formatNumber(totalForecast - totalActual, 0)}).`;
    }
    return `Forward plan for the next ${chartData.length} days across ${scope}: ${formatNumber(totalForecast, 0)} units forecast in total, shown with the empirical 10–90% residual band.`;
  }, [chartData, view, store, item]);

  if (detail.loading) return <Loading label="Loading run" />;
  if (detail.error)
    return (
      <ErrorState title="Run unavailable">
        {detail.error.message}
        <Link className="button" href="/forecasts" style={{ marginTop: "0.5rem" }}>
          Back to forecasts
        </Link>
      </ErrorState>
    );
  if (!detail.data) return null;

  const { run, job, dataset, per_series_metrics, weak_series } = detail.data;
  const baselineRow = comparison.data?.rows.find((row) => row.model_key === "seasonal_naive") ?? null;
  const modelRow = comparison.data?.rows.find((row) => row.run_id === run.id) ?? null;

  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link href="/forecasts">Forecasts</Link> / run #{run.id}
          </>
        }
        title={run.label}
        description={
          <>
            Dataset <Link href={dataset.id ? `/datasets/${dataset.id}` : "/datasets"}>{dataset.name}</Link> · version{" "}
            {dataset.version} · seed {run.seed} · trained {formatDate(run.train_start)} → {formatDate(run.train_end)} ·
            holdout {formatDate(run.test_start)} → {formatDate(run.test_end)}
          </>
        }
        actions={
          <>
            {run.is_selected ? <Badge tone="teal">Selected for planning</Badge> : <Badge tone="neutral">Comparison run</Badge>}
            <a className="button small" href={`/api/v1/forecast-runs/${run.id}/exports/forecast.csv`}>
              Forecast CSV
            </a>
            <a className="button small" href={`/api/v1/forecast-runs/${run.id}/exports/metrics.csv`}>
              Metrics CSV
            </a>
            <a className="button small" href={`/api/v1/forecast-runs/${run.id}/exports/report.json`}>
              Report JSON
            </a>
          </>
        }
      />

      <Notice tone="info" title="Forecast mode">
        {HORIZON_NOTICE} The empirical band comes from holdout residuals; it is descriptive, not calibrated.
      </Notice>

      <div className="grid grid-kpi">
        {(["wape", "mae", "rmse", "mase", "bias"] as const).map((metric) => (
          <div className="kpi" key={metric} title={METRIC_DEFINITIONS[metric].definition}>
            <span className="kpi-label">
              {METRIC_DEFINITIONS[metric].label}
              <span aria-hidden="true" style={{ color: "var(--ink-faint)" }}>
                ⓘ
              </span>
            </span>
            <span className="kpi-value">
              {metric === "wape" ? formatPercent(run.metrics[metric]) : formatNumber(run.metrics[metric], metric === "mase" ? 2 : 1)}
            </span>
            <span className="kpi-hint">
              {baselineRow
                ? `baseline ${metric === "wape" ? formatPercent(baselineRow.metrics[metric]) : formatNumber(baselineRow.metrics[metric], metric === "mase" ? 2 : 1)}`
                : "no baseline in this job"}
            </span>
          </div>
        ))}
      </div>

      <Definition label="What each metric means">
        <ul className="plain" style={{ marginTop: "0.35rem" }}>
          {Object.values(METRIC_DEFINITIONS).map((definition) => (
            <li key={definition.label}>
              <strong>{definition.label}:</strong> {definition.definition}
            </li>
          ))}
        </ul>
      </Definition>

      <div className="split-main">
        <Card
          title="Actual versus forecast"
          subtitle={view === "holdout" ? "Backtest on the chronological holdout" : "Forward plan beyond the observed data"}
          actions={
            <div className="row" style={{ gap: "0.35rem" }}>
              <button
                className={`button small ${view === "holdout" ? "primary" : ""}`}
                type="button"
                onClick={() => setView("holdout")}
                aria-pressed={view === "holdout"}
              >
                Holdout
              </button>
              <button
                className={`button small ${view === "forward" ? "primary" : ""}`}
                type="button"
                onClick={() => setView("forward")}
                aria-pressed={view === "forward"}
              >
                Forward
              </button>
            </div>
          }
        >
          <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
            <div className="field">
              <label htmlFor="store-filter">Store</label>
              <select id="store-filter" value={store} onChange={(event) => setStore(event.target.value)}>
                <option value="all">All stores</option>
                {stores.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="item-filter">Item</label>
              <select id="item-filter" value={item} onChange={(event) => setItem(event.target.value)}>
                <option value="all">All items</option>
                {items.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ justifyContent: "flex-end" }}>
              <label className="checkbox-row" htmlFor="baseline-toggle">
                <input
                  id="baseline-toggle"
                  type="checkbox"
                  checked={showBaseline}
                  onChange={(event) => setShowBaseline(event.target.checked)}
                  disabled={view === "forward"}
                />
                Show baseline
              </label>
            </div>
          </div>

          {holdout.error || forward.error ? (
            <ErrorState>{holdout.error?.message ?? forward.error?.message}</ErrorState>
          ) : chartData.length === 0 ? (
            <EmptyState title="No points for this filter">Choose a different store or item.</EmptyState>
          ) : (
            <>
              <ForecastChart data={chartData} showBaseline={view === "holdout" && showBaseline} />
              <ChartLegend showBaseline={view === "holdout" && showBaseline} />
              <p className="chart-insight">{chartSummary}</p>
              <p className="sr-only">
                Chart summary: {chartSummary} Values are aggregated per date across the filtered series.
              </p>
            </>
          )}
        </Card>

        <div className="stack">
          <Card title="Model comparison" subtitle="Chronological holdout, same window for every model">
            {comparison.loading ? (
              <div className="skeleton" style={{ height: 120 }} />
            ) : (
              <>
                <div className="table-wrap" role="region" aria-label="Model comparison" tabIndex={0}>
                  <table className="data" style={{ minWidth: 260 }}>
                    <thead>
                      <tr>
                        <th scope="col">Model</th>
                        <th scope="col" className="num">WAPE</th>
                        <th scope="col" className="num">MAE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(comparison.data?.rows ?? []).map((row) => (
                        <tr key={row.run_id} className={row.run_id === run.id ? "selected-row" : undefined}>
                          <td>
                            {row.model_key === "seasonal_naive" ? "Seasonal naive" : "Gradient boosting"}
                            {row.is_selected ? <Badge tone="teal">selected</Badge> : null}
                          </td>
                          <td className="num">{formatPercent(row.metrics.wape)}</td>
                          <td className="num">{formatNumber(row.metrics.mae)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="chart-insight">
                  {compareSummary(
                    (comparison.data?.rows ?? []).map((row) => ({ model_key: row.model_key, wape: row.metrics.wape ?? null })),
                  )}
                </p>
                {modelRow?.relative_wape_vs_baseline !== null && modelRow?.relative_wape_vs_baseline !== undefined ? (
                  <SmallCaps>{relativeToBaseline(modelRow.relative_wape_vs_baseline)}</SmallCaps>
                ) : null}
                <Definition label="How was the model selected?">
                  {comparison.data?.selection_rule ?? detail.data.selection_rule}
                </Definition>
              </>
            )}
          </Card>

          <Card title="Validation folds" subtitle="Rolling origins, all ending before the holdout">
            {run.validation_folds.length === 0 ? (
              <EmptyState title="No validation folds">
                This job ran with validation disabled; model choice fell back to the holdout ordering.
              </EmptyState>
            ) : (
              <div className="table-wrap" role="region" aria-label="Validation folds" tabIndex={0}>
                <table className="data" style={{ minWidth: 240 }}>
                  <thead>
                    <tr>
                      <th scope="col">Origin</th>
                      <th scope="col" className="num">WAPE</th>
                      <th scope="col" className="num">MAE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.validation_folds.map((fold) => (
                      <tr key={fold.origin}>
                        <td>{formatDate(fold.origin)}</td>
                        <td className="num">{formatPercent(fold.metrics.wape)}</td>
                        <td className="num">{formatNumber(fold.metrics.mae)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Run configuration" subtitle="Persisted for reproducibility">
            <div className="assumption-grid">
              <div>
                <span>Forecast mode</span>
                <span>{run.forecast_mode}</span>
              </div>
              <div>
                <span>Seed</span>
                <span>{run.seed}</span>
              </div>
              <div>
                <span>Horizon</span>
                <span>{run.horizon_days} days</span>
              </div>
              <div>
                <span>Holdout</span>
                <span>{job.holdout_days} days</span>
              </div>
              <div>
                <span>Job</span>
                <span>#{job.id}</span>
              </div>
              <div>
                <span>Dataset version</span>
                <span>v{dataset.version}</span>
              </div>
              {Object.entries(run.model_config.params ?? {}).map(([key, value]) => (
                <div key={key}>
                  <span>{key}</span>
                  <span>{String(value)}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <div className="split-main">
        <Card title="Residuals on the holdout" subtitle="Actual − forecast; the distribution exposes systematic bias">
          {residuals.loading ? (
            <div className="skeleton" style={{ height: 200 }} />
          ) : residuals.error ? (
            <ErrorState>{residuals.error.message}</ErrorState>
          ) : residuals.data ? (
            <>
              <div className="grid grid-3" style={{ gap: "0.5rem" }}>
                <div className="kpi" style={{ padding: "0.6rem 0.75rem" }}>
                  <span className="kpi-label">Mean error</span>
                  <span className="kpi-value" style={{ fontSize: "1.05rem" }}>
                    {formatNumber(residuals.data.summary.mean_error)}
                  </span>
                  <span className="kpi-hint">positive = under-forecast</span>
                </div>
                <div className="kpi" style={{ padding: "0.6rem 0.75rem" }}>
                  <span className="kpi-label">Mean absolute error</span>
                  <span className="kpi-value" style={{ fontSize: "1.05rem" }}>
                    {formatNumber(residuals.data.summary.mean_abs_error)}
                  </span>
                  <span className="kpi-hint">units per series-day</span>
                </div>
                <div className="kpi" style={{ padding: "0.6rem 0.75rem" }}>
                  <span className="kpi-label">Over-forecast share</span>
                  <span className="kpi-value" style={{ fontSize: "1.05rem" }}>
                    {formatPercent(residuals.data.summary.over_forecast_share)}
                  </span>
                  <span className="kpi-hint">share of points where forecast &gt; actual</span>
                </div>
              </div>
              <ResidualChart bins={residuals.data.summary.bins} />
              <p className="chart-insight">
                {residuals.data.residuals.length} holdout points. A distribution centred away from zero indicates
                systematic bias rather than random noise; a long right tail means stock was under-forecast on
                high-demand days.
              </p>
            </>
          ) : null}
        </Card>

        <Card title="Weakest series" subtitle="Where the aggregate hides problems">
          {weak_series.length === 0 ? (
            <EmptyState title="No per-series metrics">
              WAPE is undefined for every series in this window (all-zero demand).
            </EmptyState>
          ) : (
            <div className="table-wrap table-scroll" role="region" aria-label="Weakest series" tabIndex={0}>
              <table className="data" style={{ minWidth: 280 }}>
                <caption>Top {weak_series.length} series by holdout WAPE (highest error first).</caption>
                <thead>
                  <tr>
                    <th scope="col">Series</th>
                    <th scope="col" className="num">WAPE</th>
                    <th scope="col" className="num">MAE</th>
                  </tr>
                </thead>
                <tbody>
                  {weak_series.map((row) => (
                    <tr key={row.series_id}>
                      <td>
                        <button
                          type="button"
                          className="button ghost small"
                          onClick={() => {
                            setStore(row.store);
                            setItem(row.item);
                            setView("holdout");
                          }}
                        >
                          {row.item} @ {row.store}
                        </button>
                      </td>
                      <td className="num">{formatPercent(row.wape)}</td>
                      <td className="num">{formatNumber(row.mae)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="help">
            {per_series_metrics.length} series scored. Selecting a series above filters the chart to that series.
          </p>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Limitations" subtitle="Read before acting on these numbers">
          <ul className="plain limitation-list">
            {run.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
            {detail.data.notices.map((notice) => (
              <li key={notice}>{notice}</li>
            ))}
          </ul>
        </Card>

        <Card title="Export and use" subtitle="Downloads are generated server-side and recorded in the audit log">
          <ul className="plain">
            <li>
              <a href={`/api/v1/forecast-runs/${run.id}/exports/forecast.csv`}>Forecast CSV</a> — date, store, item,
              horizon step, forecast and empirical band.
            </li>
            <li>
              <a href={`/api/v1/forecast-runs/${run.id}/exports/metrics.csv`}>Metrics CSV</a> — aggregate plus
              per-series metrics.
            </li>
            <li>
              <a href={`/api/v1/forecast-runs/${run.id}/exports/report.json`}>Report JSON</a> — full run record with
              limitations and forecast points.
            </li>
          </ul>
          <Notice tone="warn" title="Decision support only">
            These forecasts and any reorder suggestions derived from them are planning inputs. Verify stock levels and
            supplier constraints before ordering.
          </Notice>
          <Link className="button small" href="/planning">
            Create reorder suggestions
          </Link>
        </Card>
      </div>
    </>
  );
}
