"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { RunLauncher } from "@/components/RunLauncher";
import { useSession } from "@/components/SessionProvider";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  JobStatusBadge,
  Loading,
  Notice,
  PageHead,
} from "@/components/ui";
import { apiFetch, ApiError, useApi } from "@/lib/api";
import { formatDate, formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import type { DatasetSummary, Job, RunSummary } from "@/lib/types";

export default function ForecastsPage() {
  const { session } = useSession();
  const datasets = useApi<{ datasets: DatasetSummary[] }>("/api/v1/datasets");
  const jobs = useApi<{ jobs: Job[] }>("/api/v1/forecast-jobs?limit=25");
  const runs = useApi<{ runs: RunSummary[] }>("/api/v1/forecast-runs?limit=40");
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState<number | null>(null);

  const activeJob = (jobs.data?.jobs ?? []).find((job) => ["queued", "running"].includes(job.status));

  useEffect(() => {
    if (!activeJob) return;
    const timer = setInterval(() => {
      jobs.refetch();
      runs.refetch();
    }, 2500);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJob?.id, activeJob?.status]);

  const canRun = session?.role === "owner" || session?.role === "analyst";

  const act = async (jobId: number, action: "cancel" | "retry") => {
    setPending(jobId);
    setActionError(null);
    try {
      await apiFetch(`/api/v1/forecast-jobs/${jobId}/${action}`, { method: "POST" });
      jobs.refetch();
      runs.refetch();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : `Could not ${action} this job.`);
    } finally {
      setPending(null);
    }
  };

  if (jobs.loading && runs.loading) return <Loading label="Loading forecast history" />;

  return (
    <>
      <PageHead
        eyebrow="Forecasting"
        title="Forecast jobs and runs"
        description="Each job produces one run per model. The baseline is always computed so every number has something honest to be compared against."
      />

      {actionError ? <Notice tone="danger">{actionError}</Notice> : null}

      {datasets.data?.datasets?.length ? (
        <RunLauncher datasets={datasets.data.datasets} canRun={canRun} />
      ) : (
        <EmptyState title="No dataset to forecast">
          <Link className="button" href="/upload">
            Import data first
          </Link>
        </EmptyState>
      )}

      <Card title="Jobs" subtitle="Background work with structured status and failure reasons" flush>
        {jobs.error ? (
          <div style={{ padding: "1.2rem" }}>
            <ErrorState>{jobs.error.message}</ErrorState>
          </div>
        ) : (jobs.data?.jobs ?? []).length === 0 ? (
          <div style={{ padding: "1.2rem" }}>
            <EmptyState title="No jobs yet">Start a forecast above.</EmptyState>
          </div>
        ) : (
          <div className="table-wrap table-scroll" style={{ border: "none", borderRadius: 0 }} role="region" aria-label="Forecast jobs" tabIndex={0}>
            <table className="data">
              <caption>Twenty-five most recent forecast jobs.</caption>
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Status</th>
                  <th scope="col">Configuration</th>
                  <th scope="col" className="num">Progress</th>
                  <th scope="col">Created</th>
                  <th scope="col">Failure reason</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(jobs.data?.jobs ?? []).map((job) => (
                  <tr key={job.id}>
                    <td>
                      #{job.id}
                      {job.attempt > 1 ? <div style={{ fontSize: "0.72rem", color: "var(--ink-muted)" }}>attempt {job.attempt}</div> : null}
                    </td>
                    <td>
                      <JobStatusBadge status={job.status} />
                    </td>
                    <td style={{ fontSize: "0.8rem" }}>
                      horizon {job.horizon_days}d · holdout {job.holdout_days}d · {job.validation_folds} fold(s)
                      <div style={{ color: "var(--ink-muted)" }}>
                        {job.model_keys.join(", ")} · seed {job.seed}
                      </div>
                    </td>
                    <td className="num">{job.progress}%</td>
                    <td style={{ fontSize: "0.8rem" }}>{formatDateTime(job.created_at)}</td>
                    <td style={{ fontSize: "0.78rem", color: job.failure_code ? "var(--red-600)" : "var(--ink-faint)" }}>
                      {job.failure_code ? `${job.failure_code}: ${job.failure_message}` : "—"}
                    </td>
                    <td>
                      <div className="row" style={{ gap: "0.3rem" }}>
                        {canRun && ["queued", "running"].includes(job.status) ? (
                          <button
                            className="button small"
                            type="button"
                            onClick={() => void act(job.id, "cancel")}
                            disabled={pending === job.id}
                          >
                            Cancel
                          </button>
                        ) : null}
                        {canRun && ["failed", "cancelled"].includes(job.status) ? (
                          <button
                            className="button small"
                            type="button"
                            onClick={() => void act(job.id, "retry")}
                            disabled={pending === job.id}
                          >
                            Retry
                          </button>
                        ) : null}
                        <Link className="button small ghost" href={`/forecasts?job=${job.id}`}>
                          Details
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Runs" subtitle="One row per model per job; the selected model is used for planning" flush>
        {(runs.data?.runs ?? []).length === 0 ? (
          <div style={{ padding: "1.2rem" }}>
            <EmptyState title="No completed runs yet" />
          </div>
        ) : (
          <div className="table-wrap table-scroll" style={{ border: "none", borderRadius: 0 }} role="region" aria-label="Forecast runs" tabIndex={0}>
            <table className="data">
              <caption>Holdout metrics. Lower is better; WAPE is undefined when actual demand is zero.</caption>
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Model</th>
                  <th scope="col">Holdout window</th>
                  <th scope="col" className="num">WAPE</th>
                  <th scope="col" className="num">MAE</th>
                  <th scope="col" className="num">RMSE</th>
                  <th scope="col" className="num">MASE</th>
                  <th scope="col">Status</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {(runs.data?.runs ?? []).map((run) => (
                  <tr key={run.id} className={run.is_selected ? "selected-row" : undefined}>
                    <td>#{run.id}</td>
                    <td>
                      {run.label}
                      {run.is_selected ? <Badge tone="teal">selected</Badge> : null}
                    </td>
                    <td style={{ fontSize: "0.8rem" }}>
                      {formatDate(run.test_start)} → {formatDate(run.test_end)}
                    </td>
                    <td className="num">{formatPercent(run.metrics.wape)}</td>
                    <td className="num">{formatNumber(run.metrics.mae)}</td>
                    <td className="num">{formatNumber(run.metrics.rmse)}</td>
                    <td className="num">{formatNumber(run.metrics.mase, 2)}</td>
                    <td>
                      {run.job_status ? <JobStatusBadge status={run.job_status} /> : <Badge tone="neutral">—</Badge>}
                    </td>
                    <td>
                      <Link href={`/forecasts/${run.id}`}>Open →</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Notice tone="info" title="Evaluation protocol">
        Rolling-origin validation chooses the model; a single chronological holdout scores it. The holdout window is
        never used for selection, and every run records the exact train/test window, seed and hyper-parameters.
      </Notice>
    </>
  );
}
