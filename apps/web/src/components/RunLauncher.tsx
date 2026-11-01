"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { apiFetch, ApiError, useJobPolling } from "@/lib/api";
import type { DatasetSummary, Job, RunSummary } from "@/lib/types";

import { Badge, JobStatusBadge, Notice, ProgressBar } from "./ui";

interface CreateResponse {
  job: Job;
  runs: RunSummary[];
  baseline_added?: boolean;
  dispatch_mode?: string;
  idempotentReplay?: boolean;
}

export function RunLauncher({
  datasets,
  defaultDatasetId,
  canRun,
}: {
  datasets: DatasetSummary[];
  defaultDatasetId?: number | null;
  canRun: boolean;
}) {
  const router = useRouter();
  const [datasetId, setDatasetId] = useState<number | null>(defaultDatasetId ?? datasets[0]?.id ?? null);
  const [horizon, setHorizon] = useState(14);
  const [holdout, setHoldout] = useState(14);
  const [folds, setFolds] = useState(2);
  const [seed, setSeed] = useState(42);
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const selected = useMemo(() => datasets.find((dataset) => dataset.id === datasetId), [datasets, datasetId]);
  const { job } = useJobPolling(jobId, () => {
    router.refresh();
    if (jobId) {
      // Land the user on the run detail once artifacts exist.
      void apiFetch<{ runs: RunSummary[] }>(`/api/v1/forecast-jobs/${jobId}`).then((body) => {
        const selectedRun = body.runs.find((run) => run.is_selected) ?? body.runs[0];
        if (selectedRun) router.push(`/forecasts/${selectedRun.id}`);
      });
    }
  });

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!datasetId) return;
    setSubmitting(true);
    setError(null);
    try {
      const body = await apiFetch<CreateResponse>("/api/v1/forecast-jobs", {
        method: "POST",
        body: JSON.stringify({
          dataset_id: datasetId,
          horizon_days: horizon,
          holdout_days: holdout,
          validation_folds: folds,
          seed,
          model_keys: ["seasonal_naive", "hist_gradient_boosting"],
          idempotency_key: `ui-${datasetId}-${horizon}-${holdout}-${folds}-${seed}-${Date.now()}`,
        }),
      });
      setJobId(body.job.id);
      if (body.job.status === "failed") {
        setError(body.job.failure_message ?? "The job could not be started.");
      }
    } catch (caught) {
      const message =
        caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : "Could not start the job.";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const busy = submitting || (job ? ["queued", "running"].includes(job.status) : false);

  return (
    <section className="card" aria-labelledby="run-launcher-title">
      <div className="card-head">
        <div>
          <h2 id="run-launcher-title">Run a forecast</h2>
          <p>
            Trains the baseline and the gradient-boosting model, validates on rolling origins, then scores a
            chronological holdout. Nothing is tuned on the holdout.
          </p>
        </div>
        {job ? <JobStatusBadge status={job.status as Job["status"]} /> : null}
      </div>

      {!canRun ? (
        <Notice tone="info">Your role is read-only. Ask an analyst or owner to run forecasts.</Notice>
      ) : null}

      <form className="stack" onSubmit={submit} aria-describedby="run-limits">
        <div className="form-grid">
          <div className="field">
            <label htmlFor="dataset">Dataset</label>
            <select
              id="dataset"
              value={datasetId ?? ""}
              onChange={(event) => setDatasetId(Number(event.target.value))}
              disabled={!canRun}
            >
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name} (v{dataset.current_version?.version ?? "—"})
                </option>
              ))}
            </select>
            {selected?.current_version ? (
              <span className="help">
                {selected.current_version.series_count} series · {selected.current_version.row_count.toLocaleString()} rows
              </span>
            ) : null}
          </div>

          <div className="field">
            <label htmlFor="horizon">Forecast horizon (days)</label>
            <input
              id="horizon"
              type="number"
              min={1}
              max={90}
              value={horizon}
              onChange={(event) => setHorizon(Number(event.target.value))}
              disabled={!canRun}
            />
            <span className="help">Fixed multi-step, 1–90 days</span>
          </div>

          <div className="field">
            <label htmlFor="holdout">Holdout window (days)</label>
            <input
              id="holdout"
              type="number"
              min={7}
              max={90}
              value={holdout}
              onChange={(event) => setHoldout(Number(event.target.value))}
              disabled={!canRun}
            />
            <span className="help">Chronological, most recent days</span>
          </div>

          <div className="field">
            <label htmlFor="folds">Validation folds</label>
            <input
              id="folds"
              type="number"
              min={0}
              max={5}
              value={folds}
              onChange={(event) => setFolds(Number(event.target.value))}
              disabled={!canRun}
            />
            <span className="help">Rolling origins before the holdout</span>
          </div>

          <div className="field">
            <label htmlFor="seed">Random seed</label>
            <input
              id="seed"
              type="number"
              min={0}
              max={2147483647}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
              disabled={!canRun}
            />
            <span className="help">Same seed → same results</span>
          </div>
        </div>

        <p className="help" id="run-limits">
          The seasonal-naive baseline is always included. Jobs are bounded by row, series, horizon and time limits.
        </p>

        {error ? (
          <Notice tone="danger" title="The forecast did not start">
            {error}
          </Notice>
        ) : null}

        {job && ["queued", "running"].includes(job.status) ? (
          <div className="stack" style={{ gap: "0.5rem" }}>
            <ProgressBar value={job.progress} label={job.stage ?? job.status} />
            <span style={{ fontSize: "0.8rem", color: "var(--ink-muted)" }}>
              Running in the background. This page updates automatically.
            </span>
          </div>
        ) : null}

        {job && job.status === "failed" ? (
          <Notice tone="danger" title="Forecast failed">
            {job.stage ?? "The worker reported a failure"} — open the job history to retry.
          </Notice>
        ) : null}

        <div className="row">
          <button className="button primary" type="submit" disabled={busy || !canRun || !datasetId}>
            {busy ? "Forecast running…" : "Start forecast"}
          </button>
          <Badge tone="neutral">Deterministic seed</Badge>
          <Badge tone="neutral">Baseline included</Badge>
        </div>
      </form>
    </section>
  );
}
