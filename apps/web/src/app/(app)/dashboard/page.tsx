"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { RunLauncher } from "@/components/RunLauncher";
import { compareSummary, WapeBars } from "@/components/charts";
import { useSession } from "@/components/SessionProvider";
import {
  Badge,
  Card,
  Definition,
  EmptyState,
  ErrorState,
  JobStatusBadge,
  Kpi,
  Loading,
  Notice,
  PageHead,
  SmallCaps,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { formatDate, formatNumber, formatPercent, formatUnits, METRIC_DEFINITIONS, relativeToBaseline } from "@/lib/format";
import type {
  AlertsResponse,
  ComparisonRow,
  DatasetSummary,
  Job,
  RunSummary,
  Suggestion,
} from "@/lib/types";

export default function DashboardPage() {
  const { session } = useSession();
  const datasets = useApi<{ datasets: DatasetSummary[] }>("/api/v1/datasets");
  const jobs = useApi<{ jobs: Job[] }>("/api/v1/forecast-jobs?limit=6");
  const runs = useApi<{ runs: RunSummary[] }>("/api/v1/forecast-runs?limit=6");
  const alerts = useApi<AlertsResponse>("/api/v1/alerts");
  const suggestions = useApi<{ suggestions: Suggestion[] }>("/api/v1/inventory-suggestions?only_orders=true&limit=200");

  const latestRun = runs.data?.runs?.[0] ?? null;
  const comparison = useApi<{ rows: ComparisonRow[] }>(
    latestRun ? `/api/v1/forecast-runs/${latestRun.id}/comparison` : null,
    [latestRun?.id],
  );

  const [datasetFilter, setDatasetFilter] = useState<number | "all">("all");
  const activeDataset = useMemo(() => {
    if (!datasets.data?.datasets?.length) return null;
    if (datasetFilter === "all") return datasets.data.datasets[0];
    return datasets.data.datasets.find((dataset) => dataset.id === datasetFilter) ?? datasets.data.datasets[0];
  }, [datasets.data, datasetFilter]);

  const quality = activeDataset?.current_version?.quality;
  const zeroShare =
    quality && quality.row_count_out > 0 ? quality.zero_demand_days / quality.row_count_out : 0;

  if (datasets.loading && jobs.loading) {
    return <Loading label="Loading workspace overview" />;
  }

  if (datasets.error) {
    return (
      <ErrorState title="Could not load your workspace">
        {datasets.error.message}
        <button className="button" type="button" onClick={datasets.refetch} style={{ marginTop: "0.5rem" }}>
          Retry
        </button>
      </ErrorState>
    );
  }

  const datasetList = datasets.data?.datasets ?? [];
  const canRun = session?.role === "owner" || session?.role === "analyst";
  const openAlerts = alerts.data?.alerts ?? [];
  const orderedUnits = (suggestions.data?.suggestions ?? []).reduce((total, row) => total + row.suggested_qty, 0);
  const modelRow = comparison.data?.rows.find((row) => row.model_key === "hist_gradient_boosting");
  const baselineRow = comparison.data?.rows.find((row) => row.model_key === "seasonal_naive");

  return (
    <>
      <PageHead
        eyebrow="Workspace overview"
        title="Demand planning at a glance"
        description={
          <>
            Everything here runs on synthetic demo data. Holdout metrics describe one chronological window of this
            dataset — they are not a real-world benchmark.
          </>
        }
        actions={
          <>
            {datasetList.length > 1 ? (
              <label className="field" style={{ minWidth: 200 }}>
                <span className="sr-only">Filter by dataset</span>
                <select
                  value={datasetFilter}
                  onChange={(event) =>
                    setDatasetFilter(event.target.value === "all" ? "all" : Number(event.target.value))
                  }
                  aria-label="Filter by dataset"
                >
                  <option value="all">All datasets</option>
                  {datasetList.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <Link className="button" href="/forecasts">
              Forecast history
            </Link>
          </>
        }
      />

      {datasetList.length === 0 ? (
        <EmptyState title="No datasets yet">
          Import a CSV or generate the synthetic demo dataset to start forecasting.
          <Link className="button primary" href="/upload" style={{ marginTop: "0.6rem" }}>
            Import data
          </Link>
        </EmptyState>
      ) : null}

      <div className="grid grid-kpi">
        <Kpi
          label="Active dataset"
          value={activeDataset?.name ?? "—"}
          hint={
            activeDataset?.current_version
              ? `v${activeDataset.current_version.version} · ${formatDate(activeDataset.current_version.date_min)} → ${formatDate(activeDataset.current_version.date_max)}`
              : "No imported version"
          }
          accent
        />
        <Kpi
          label="Series tracked"
          value={formatUnits(activeDataset?.current_version?.series_count ?? 0)}
          hint={`${formatUnits(activeDataset?.current_version?.row_count ?? 0)} series-days`}
        />
        <Kpi
          label="Latest holdout WAPE"
          value={formatPercent(modelRow?.metrics.wape)}
          hint={
            modelRow && baselineRow
              ? `Baseline ${formatPercent(baselineRow.metrics.wape)} · ${relativeToBaseline(modelRow.relative_wape_vs_baseline)}`
              : "Run a forecast to see model quality"
          }
          title={METRIC_DEFINITIONS.wape.definition}
        />
        <Kpi
          label="Open alerts"
          value={formatUnits(alerts.data?.counts?.open ?? openAlerts.length)}
          hint={
            openAlerts.filter((alert) => alert.severity === "critical").length > 0
              ? `${openAlerts.filter((alert) => alert.severity === "critical").length} critical`
              : "No critical alerts"
          }
        />
        <Kpi
          label="Units suggested"
          value={formatUnits(orderedUnits)}
          hint={`${suggestions.data?.suggestions?.length ?? 0} series below reorder point`}
        />
      </div>

      <div className="split-main">
        <Card
          title="Model versus baseline"
          subtitle="Holdout window for the most recent completed run"
          actions={
            latestRun ? (
              <Link className="button small" href={`/forecasts/${latestRun.id}`}>
                Open run detail
              </Link>
            ) : null
          }
        >
          {!latestRun ? (
            <EmptyState title="No completed forecast yet">
              Start a forecast below; results, metrics and exports appear here automatically.
            </EmptyState>
          ) : (
            <>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <SmallCaps>
                  {latestRun.label} · holdout {formatDate(latestRun.test_start)} → {formatDate(latestRun.test_end)}
                </SmallCaps>
                <Badge tone={latestRun.is_selected ? "teal" : "neutral"}>
                  {latestRun.is_selected ? "Selected model" : "Comparison run"}
                </Badge>
              </div>
              <WapeBars rows={(comparison.data?.rows ?? []).map((row) => ({ ...row, wape: row.metrics.wape ?? null }))} />
              <p className="chart-insight">
                {compareSummary(
                  (comparison.data?.rows ?? []).map((row) => ({ model_key: row.model_key, wape: row.metrics.wape ?? null })),
                )}
              </p>
              <div className="grid grid-3" style={{ gap: "0.6rem" }}>
                {(["mae", "rmse", "mase"] as const).map((metric) => (
                  <div key={metric} className="kpi" style={{ padding: "0.6rem 0.75rem" }}>
                    <span className="kpi-label" title={METRIC_DEFINITIONS[metric].definition}>
                      {METRIC_DEFINITIONS[metric].label}
                    </span>
                    <span className="kpi-value" style={{ fontSize: "1.1rem" }}>
                      {metric === "mase" ? formatNumber(modelRow?.metrics.mase, 2) : formatNumber(modelRow?.metrics[metric])}
                      <small style={{ marginLeft: "0.35rem" }}>
                        base {metric === "mase" ? formatNumber(baselineRow?.metrics.mase, 2) : formatNumber(baselineRow?.metrics[metric])}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
              <Definition label="What do these metrics mean?">
                <ul className="plain" style={{ marginTop: "0.35rem" }}>
                  {Object.values(METRIC_DEFINITIONS).map((definition) => (
                    <li key={definition.label}>
                      <strong>{definition.label}:</strong> {definition.definition}
                    </li>
                  ))}
                </ul>
              </Definition>
            </>
          )}
        </Card>

        <div className="stack">
          <Card
            title="Alerts"
            subtitle="Derived rules, re-evaluated whenever this page loads"
            actions={<Link className="button small" href="/alerts">All alerts</Link>}
          >
            {alerts.error ? (
              <ErrorState>{alerts.error.message}</ErrorState>
            ) : openAlerts.length === 0 ? (
              <EmptyState title="No open alerts">
                Low projected stock, high forecast error, stale datasets and failed jobs appear here.
              </EmptyState>
            ) : (
              <ul className="stack" style={{ gap: "0.65rem", listStyle: "none", padding: 0, margin: 0 }}>
                {openAlerts.slice(0, 4).map((alert) => (
                  <li key={alert.id} className="stack" style={{ gap: "0.15rem" }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <strong style={{ fontSize: "0.87rem" }}>{alert.title}</strong>
                      <Badge tone={alert.severity === "critical" ? "danger" : alert.severity === "warning" ? "warn" : "info"}>
                        {alert.severity}
                      </Badge>
                    </div>
                    <span style={{ fontSize: "0.8rem", color: "var(--ink-muted)" }}>{alert.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Data quality" subtitle="From the active dataset version">
            {!quality ? (
              <EmptyState title="No imported version" />
            ) : (
              <div className="stack" style={{ gap: "0.6rem" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <SmallCaps>Fingerprint</SmallCaps>
                  <code style={{ fontSize: "0.75rem" }}>{activeDataset?.current_version?.fingerprint_short}</code>
                </div>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <SmallCaps>Zero-demand series-days</SmallCaps>
                  <span style={{ fontSize: "0.83rem" }}>{formatPercent(zeroShare)}</span>
                </div>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <SmallCaps>Duplicates summed</SmallCaps>
                  <span style={{ fontSize: "0.83rem" }}>{formatNumber(quality.duplicate_rows_summed, 0)}</span>
                </div>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <SmallCaps>Missing days filled</SmallCaps>
                  <span style={{ fontSize: "0.83rem" }}>{formatNumber(quality.missing_dates_filled, 0)}</span>
                </div>
                {quality.warnings.length > 0 ? (
                  <Notice tone="warn" title={`${quality.warnings.length} ingestion warning(s)`}>
                    <ul className="plain" style={{ marginTop: "0.3rem" }}>
                      {quality.warnings.slice(0, 3).map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </Notice>
                ) : (
                  <Notice tone="ok">No ingestion warnings for this version.</Notice>
                )}
                {activeDataset ? (
                  <Link className="button small" href={`/datasets/${activeDataset.id}`}>
                    Inspect dataset
                  </Link>
                ) : null}
              </div>
            )}
          </Card>
        </div>
      </div>

      <Card title="Recent forecast jobs" subtitle="Queued, running and finished background work" flush>
        {jobs.error ? (
          <div style={{ padding: "1.2rem" }}>
            <ErrorState>{jobs.error.message}</ErrorState>
          </div>
        ) : (jobs.data?.jobs ?? []).length === 0 ? (
          <div style={{ padding: "1.2rem" }}>
            <EmptyState title="No jobs yet">Start a forecast below to create the first one.</EmptyState>
          </div>
        ) : (
          <div className="table-wrap" style={{ border: "none", borderRadius: 0 }}>
            <table className="data">
              <caption>Most recent six forecast jobs. Status updates live while a job runs.</caption>
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">Horizon</th>
                  <th scope="col" className="num">Holdout</th>
                  <th scope="col">Created</th>
                  <th scope="col">Duration</th>
                </tr>
              </thead>
              <tbody>
                {(jobs.data?.jobs ?? []).map((job) => (
                  <tr key={job.id}>
                    <td>#{job.id}</td>
                    <td>
                      <JobStatusBadge status={job.status} />
                      {job.failure_message ? (
                        <div style={{ fontSize: "0.75rem", color: "var(--red-600)", marginTop: "0.2rem" }}>
                          {job.failure_message}
                        </div>
                      ) : null}
                    </td>
                    <td className="num">{job.horizon_days}d</td>
                    <td className="num">{job.holdout_days}d</td>
                    <td>{formatDate(job.created_at)}</td>
                    <td>{job.duration_seconds ? `${job.duration_seconds}s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {datasetList.length > 0 ? (
        <RunLauncher datasets={datasetList} defaultDatasetId={activeDataset?.id ?? null} canRun={canRun} />
      ) : null}

      <Notice tone="info" title="How to read this workspace">
        A forecast is only useful if it beats the seasonal-naive baseline on a window the model never saw. Open any
        run to inspect the comparison, the residual distribution, the weakest series and the exported report.
      </Notice>
    </>
  );
}
