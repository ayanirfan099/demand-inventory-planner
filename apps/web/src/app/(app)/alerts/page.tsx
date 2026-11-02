"use client";

import Link from "next/link";
import { useState } from "react";

import { useSession } from "@/components/SessionProvider";
import { Badge, Card, EmptyState, ErrorState, Loading, Notice, PageHead } from "@/components/ui";
import { apiFetch, ApiError, useApi } from "@/lib/api";
import { formatDateTime, formatPercent } from "@/lib/format";
import type { AlertsResponse } from "@/lib/types";

const SEVERITY_TONE = { info: "info", warning: "warn", critical: "danger" } as const;

export default function AlertsPage() {
  const { session } = useSession();
  const [filter, setFilter] = useState<"open" | "acknowledged" | "all">("open");
  const alerts = useApi<AlertsResponse>(`/api/v1/alerts?status=${filter}`);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<number | null>(null);

  const canWrite = session?.role === "owner" || session?.role === "analyst";

  const act = async (alertId: number, status: "acknowledged" | "resolved") => {
    setPending(alertId);
    setError(null);
    try {
      await apiFetch(`/api/v1/alerts/${alertId}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      alerts.refetch();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update this alert.");
    } finally {
      setPending(null);
    }
  };

  if (alerts.loading) return <Loading label="Evaluating alert rules" />;
  if (alerts.error)
    return (
      <ErrorState title="Could not evaluate alerts">
        {alerts.error.message}
        <button className="button" type="button" onClick={alerts.refetch} style={{ marginTop: "0.5rem" }}>
          Retry
        </button>
      </ErrorState>
    );

  const rows = alerts.data?.alerts ?? [];

  return (
    <>
      <PageHead
        eyebrow="Operations"
        title="Alerts"
        description="Low projected stock, high forecast error, stale datasets and failed jobs. Rules run when this page loads and each rule writes at most one alert."
        actions={
          <div className="row" style={{ gap: "0.3rem" }}>
            {(["open", "acknowledged", "all"] as const).map((option) => (
              <button
                key={option}
                className={`button small ${filter === option ? "primary" : ""}`}
                type="button"
                onClick={() => setFilter(option)}
                aria-pressed={filter === option}
              >
                {option}
              </button>
            ))}
          </div>
        }
      />

      {error ? <Notice tone="danger">{error}</Notice> : null}

      <div className="grid grid-kpi">
        <div className="kpi">
          <span className="kpi-label">Open</span>
          <span className="kpi-value">{alerts.data?.counts?.open ?? 0}</span>
          <span className="kpi-hint">awaiting review</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Acknowledged</span>
          <span className="kpi-value">{alerts.data?.counts?.acknowledged ?? 0}</span>
          <span className="kpi-hint">seen by a planner</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">High-error threshold</span>
          <span className="kpi-value">WAPE {formatPercent(alerts.data?.thresholds?.high_error_wape ?? 0.5, 0)}</span>
          <span className="kpi-hint">configurable per deployment</span>
        </div>
      </div>

      <Card title="Alert feed" flush>
        {rows.length === 0 ? (
          <div style={{ padding: "1.2rem" }}>
            <EmptyState title={`No ${filter === "all" ? "" : filter} alerts`}>
              Low projected stock appears after reorder suggestions are generated; failed jobs appear immediately.
            </EmptyState>
          </div>
        ) : (
          <div className="table-wrap" style={{ border: "none", borderRadius: 0 }} role="region" aria-label="Alerts" tabIndex={0}>
            <table className="data">
              <caption>Alerts for the active organization only.</caption>
              <thead>
                <tr>
                  <th scope="col">Severity</th>
                  <th scope="col">Alert</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Raised</th>
                  <th scope="col">Status</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((alert) => (
                  <tr key={alert.id}>
                    <td>
                      <Badge tone={SEVERITY_TONE[alert.severity] ?? "neutral"}>{alert.severity}</Badge>
                    </td>
                    <td>
                      <strong style={{ fontSize: "0.85rem" }}>{alert.title}</strong>
                      <div style={{ fontSize: "0.72rem", color: "var(--ink-faint)" }}>{alert.kind}</div>
                    </td>
                    <td style={{ fontSize: "0.8rem", maxWidth: 380 }}>{alert.detail}</td>
                    <td style={{ fontSize: "0.78rem" }}>{formatDateTime(alert.created_at)}</td>
                    <td>
                      <Badge tone={alert.status === "open" ? "warn" : alert.status === "resolved" ? "ok" : "neutral"}>
                        {alert.status}
                      </Badge>
                    </td>
                    <td>
                      <div className="row" style={{ gap: "0.25rem" }}>
                        {canWrite && alert.status === "open" ? (
                          <button
                            className="button small"
                            type="button"
                            onClick={() => void act(alert.id, "acknowledged")}
                            disabled={pending === alert.id}
                          >
                            Acknowledge
                          </button>
                        ) : null}
                        {alert.run_id ? <Link className="button small ghost" href={`/forecasts/${alert.run_id}`}>Run</Link> : null}
                        {alert.job_id ? (
                          <Link className="button small ghost" href="/forecasts">
                            Job
                          </Link>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Rule definitions" subtitle="Deterministic and deduplicated">
        <ul className="plain">
          <li>
            <strong>low_projected_stock</strong> — projected on-hand at the end of the planning window falls below
            safety stock; raised when suggestions are generated.
          </li>
          <li>
            <strong>high_forecast_error</strong> — the selected run&apos;s holdout WAPE exceeds the configured threshold.
          </li>
          <li>
            <strong>stale_dataset</strong> — the newest demand in a dataset is older than the staleness window.
          </li>
          <li>
            <strong>failed_job</strong> — a forecast job failed and needs attention; retry from the forecast history.
          </li>
        </ul>
      </Card>
    </>
  );
}
