"use client";

import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Loading, PageHead } from "@/components/ui";
import { useApi } from "@/lib/api";
import { bytesToSize, formatDate, formatNumber, formatPercent } from "@/lib/format";
import type { DatasetSummary } from "@/lib/types";

export default function DatasetsPage() {
  const { data, loading, error, refetch } = useApi<{ datasets: DatasetSummary[] }>("/api/v1/datasets");

  if (loading) return <Loading label="Loading datasets" />;
  if (error)
    return (
      <ErrorState title="Could not load datasets">
        {error.message}
        <button className="button" type="button" onClick={refetch} style={{ marginTop: "0.5rem" }}>
          Retry
        </button>
      </ErrorState>
    );

  const datasets = data?.datasets ?? [];

  return (
    <>
      <PageHead
        eyebrow="Data"
        title="Datasets"
        description="Each import creates an immutable, fingerprinted version. Forecast jobs always reference the exact version they ran on."
        actions={
          <Link className="button primary" href="/upload">
            Import data
          </Link>
        }
      />

      {datasets.length === 0 ? (
        <EmptyState title="No datasets in this workspace">
          <Link className="button" href="/upload">
            Import a CSV or generate demo data
          </Link>
        </EmptyState>
      ) : (
        <div className="grid grid-2">
          {datasets.map((dataset) => {
            const version = dataset.current_version;
            const quality = version?.quality;
            const zeroShare =
              quality && quality.row_count_out ? quality.zero_demand_days / quality.row_count_out : 0;
            return (
              <Card
                key={dataset.id}
                title={dataset.name}
                subtitle={dataset.description ?? "No description"}
                actions={<Badge tone={dataset.source === "upload" ? "info" : "teal"}>{dataset.source}</Badge>}
              >
                {version ? (
                  <>
                    <div className="grid grid-3" style={{ gap: "0.5rem" }}>
                      <div>
                        <div className="kpi-label">Version</div>
                        <div style={{ fontWeight: 650 }}>v{version.version}</div>
                      </div>
                      <div>
                        <div className="kpi-label">Series</div>
                        <div style={{ fontWeight: 650 }}>{formatNumber(version.series_count, 0)}</div>
                      </div>
                      <div>
                        <div className="kpi-label">Rows</div>
                        <div style={{ fontWeight: 650 }}>{formatNumber(version.row_count, 0)}</div>
                      </div>
                      <div>
                        <div className="kpi-label">Window</div>
                        <div style={{ fontSize: "0.82rem" }}>
                          {formatDate(version.date_min)} → {formatDate(version.date_max)}
                        </div>
                      </div>
                      <div>
                        <div className="kpi-label">Zero share</div>
                        <div style={{ fontSize: "0.82rem" }}>{formatPercent(zeroShare)}</div>
                      </div>
                      <div>
                        <div className="kpi-label">Size</div>
                        <div style={{ fontSize: "0.82rem" }}>{bytesToSize(version.byte_size)}</div>
                      </div>
                    </div>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <code style={{ fontSize: "0.72rem", color: "var(--ink-muted)" }}>
                        {version.fingerprint.slice(0, 26)}…
                      </code>
                      {quality && quality.warnings.length > 0 ? (
                        <Badge tone="warn">{quality.warnings.length} warning(s)</Badge>
                      ) : (
                        <Badge tone="ok">Clean import</Badge>
                      )}
                    </div>
                    <div className="row">
                      <Link className="button small" href={`/datasets/${dataset.id}`}>
                        Open dataset
                      </Link>
                      <a
                        className="button small ghost"
                        href={`/api/v1/datasets/${dataset.id}/versions/${version.id}/download`}
                      >
                        Download CSV
                      </a>
                    </div>
                  </>
                ) : (
                  <EmptyState title="No imported version yet" />
                )}
              </Card>
            );
          })}
        </div>
      )}

      <Card title="Why versions are immutable" subtitle="Reproducibility and audit">
        <ul className="plain">
          <li>Every version keeps its own canonical CSV plus a SHA-256 fingerprint of the content.</li>
          <li>Re-uploading identical content returns the existing version instead of duplicating data.</li>
          <li>Runs reference a dataset version id, so re-importing data never rewrites historical results.</li>
          <li>Uploaded files are parsed as text only — nothing from a CSV is ever executed.</li>
        </ul>
      </Card>
    </>
  );
}
