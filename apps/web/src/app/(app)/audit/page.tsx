"use client";

import { useSession } from "@/components/SessionProvider";
import { Badge, Card, EmptyState, ErrorState, Loading, Notice, PageHead } from "@/components/ui";
import { useApi } from "@/lib/api";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { AuditRow } from "@/lib/types";

interface ExportRow {
  id: number;
  kind: string;
  run_id: number | null;
  filename: string;
  content_type: string;
  byte_size: number;
  status: string;
  created_at: string;
}

export default function AuditPage() {
  const { session } = useSession();
  const isOwner = session?.role === "owner";
  const events = useApi<{ events: AuditRow[] }>(isOwner ? "/api/v1/audit-events?limit=100" : null);
  const exports = useApi<{ exports: ExportRow[] }>(isOwner ? "/api/v1/exports?limit=50" : null);

  if (!isOwner) {
    return (
      <>
        <PageHead title="Audit trail" description="Append-only record of data, job and planning actions." />
        <Notice tone="info" title="Owner-only view">
          Your role is <strong>{session?.role}</strong>. Auditors and data owners can read the audit trail.
        </Notice>
      </>
    );
  }

  if (events.loading) return <Loading label="Loading audit trail" />;
  if (events.error) return <ErrorState title="Audit trail unavailable">{events.error.message}</ErrorState>;

  const rows = events.data?.events ?? [];

  return (
    <>
      <PageHead
        eyebrow="Governance"
        title="Audit trail"
        description="Every import, job, suggestion and export writes an event with the acting user and request id. Events are append-only; there is no edit or delete path in the API."
      />

      <div className="grid grid-kpi">
        <div className="kpi">
          <span className="kpi-label">Events shown</span>
          <span className="kpi-value">{rows.length}</span>
          <span className="kpi-hint">most recent 100</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Exports recorded</span>
          <span className="kpi-value">{exports.data?.exports?.length ?? 0}</span>
          <span className="kpi-hint">downloads are audited too</span>
        </div>
      </div>

      <Card title="Events" flush>
        {rows.length === 0 ? (
          <div style={{ padding: "1.2rem" }}>
            <EmptyState title="No events yet">
              Import a dataset or run a forecast to populate the trail.
            </EmptyState>
          </div>
        ) : (
          <div className="table-wrap table-scroll" style={{ border: "none", borderRadius: 0 }}>
            <table className="data">
              <caption>Newest first. Payloads are trimmed to the fields relevant to the action.</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Action</th>
                  <th scope="col">Entity</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Payload</th>
                  <th scope="col">Request</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((event) => (
                  <tr key={event.id}>
                    <td style={{ fontSize: "0.78rem" }}>{formatDateTime(event.created_at)}</td>
                    <td>
                      <Badge tone="neutral">{event.action}</Badge>
                    </td>
                    <td style={{ fontSize: "0.8rem" }}>
                      {event.entity_type}
                      {event.entity_id ? ` #${event.entity_id}` : ""}
                    </td>
                    <td style={{ fontSize: "0.8rem" }}>{event.actor_user_id ?? "system"}</td>
                    <td>
                      <code style={{ fontSize: "0.72rem", whiteSpace: "pre-wrap", display: "block", maxWidth: 460 }}>
                        {JSON.stringify(event.payload)}
                      </code>
                    </td>
                    <td>
                      <code style={{ fontSize: "0.7rem", color: "var(--ink-faint)" }}>
                        {event.request_id ? event.request_id.slice(0, 10) : "—"}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Downloads" subtitle="Report and data exports generated server-side" flush>
        {(exports.data?.exports ?? []).length === 0 ? (
          <div style={{ padding: "1.2rem" }}>
            <EmptyState title="No exports yet">Export a forecast or report from any run.</EmptyState>
          </div>
        ) : (
          <div className="table-wrap" style={{ border: "none", borderRadius: 0 }}>
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Filename</th>
                  <th scope="col" className="num">Bytes</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {(exports.data?.exports ?? []).map((row) => (
                  <tr key={row.id}>
                    <td style={{ fontSize: "0.78rem" }}>{formatDateTime(row.created_at)}</td>
                    <td>{row.kind}</td>
                    <td>
                      <code style={{ fontSize: "0.75rem" }}>{row.filename}</code>
                    </td>
                    <td className="num">{formatNumber(row.byte_size, 0)}</td>
                    <td>
                      <Badge tone="ok">{row.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
