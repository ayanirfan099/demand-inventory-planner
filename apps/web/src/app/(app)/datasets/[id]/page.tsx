"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { useSession } from "@/components/SessionProvider";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Notice,
  PageHead,
  SmallCaps,
} from "@/components/ui";
import { apiFetch, ApiError, useApi } from "@/lib/api";
import { bytesToSize, formatDate, formatNumber, formatPercent } from "@/lib/format";
import type { DatasetDetail, SeriesRow } from "@/lib/types";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface DemandPoint {
  date: string;
  quantity: number;
  series_id: number;
}

export default function DatasetDetailPage() {
  const params = useParams<{ id: string }>();
  const datasetId = Number(params.id);
  const { session } = useSession();
  const detail = useApi<DatasetDetail>(`/api/v1/datasets/${datasetId}`);
  const demand = useApi<{ points: DemandPoint[] }>(`/api/v1/datasets/${datasetId}/demand?days=90`);

  const [editing, setEditing] = useState<Record<number, number>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const chartData = useMemo(() => {
    const totals = new Map<string, number>();
    for (const point of demand.data?.points ?? []) {
      totals.set(point.date, (totals.get(point.date) ?? 0) + point.quantity);
    }
    return [...totals.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, total]) => ({ date, total }));
  }, [demand.data]);

  const canEdit = session?.role === "owner" || session?.role === "analyst";

  const saveOnHand = async (row: SeriesRow) => {
    const value = editing[row.id];
    if (value === undefined || Number.isNaN(value)) return;
    setSavingId(row.id);
    setError(null);
    setMessage(null);
    try {
      await apiFetch(`/api/v1/datasets/${datasetId}/series/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ on_hand: value }),
      });
      setMessage(`Updated on-hand for ${row.store} / ${row.item} to ${value}.`);
      setEditing((current) => {
        const next = { ...current };
        delete next[row.id];
        return next;
      });
      detail.refetch();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update on-hand stock.");
    } finally {
      setSavingId(null);
    }
  };

  if (detail.loading) return <Loading label="Loading dataset" />;
  if (detail.error)
    return (
      <ErrorState title="Dataset unavailable">
        {detail.error.message}
        <Link className="button" href="/datasets" style={{ marginTop: "0.5rem" }}>
          Back to datasets
        </Link>
      </ErrorState>
    );
  if (!detail.data) return null;

  const { dataset, versions, series } = detail.data;
  const current = dataset.current_version;
  const quality = current?.quality;
  const zeroShare = quality && quality.row_count_out ? quality.zero_demand_days / quality.row_count_out : 0;

  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link href="/datasets">Datasets</Link> / {dataset.name}
          </>
        }
        title={dataset.name}
        description={dataset.description ?? "No description for this dataset."}
        actions={
          <>
            <Badge tone={dataset.source === "upload" ? "info" : "teal"}>{dataset.source}</Badge>
            {current ? (
              <a className="button small" href={`/api/v1/datasets/${dataset.id}/versions/${current.id}/download`}>
                Download CSV
              </a>
            ) : null}
            <Link className="button primary small" href="/forecasts">
              Run forecast
            </Link>
          </>
        }
      />

      {quality?.notice ? <Notice tone="warn" title="Synthetic demo data">{quality.notice}</Notice> : null}
      {message ? <Notice tone="ok">{message}</Notice> : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}

      <div className="grid grid-kpi">
        <div className="kpi accent">
          <span className="kpi-label">Current version</span>
          <span className="kpi-value">v{current?.version ?? "—"}</span>
          <span className="kpi-hint">{current ? formatDate(current.created_at) : "no import yet"}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Series</span>
          <span className="kpi-value">{formatNumber(series.length, 0)}</span>
          <span className="kpi-hint">{formatNumber(current?.row_count ?? 0, 0)} series-days stored</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Window</span>
          <span className="kpi-value" style={{ fontSize: "1rem" }}>
            {formatDate(current?.date_min)} → {formatDate(current?.date_max)}
          </span>
          <span className="kpi-hint">daily grain, calendar normalised</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Zero-demand share</span>
          <span className="kpi-value">{formatPercent(zeroShare)}</span>
          <span className="kpi-hint">high shares make WAPE unstable</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Stored size</span>
          <span className="kpi-value" style={{ fontSize: "1rem" }}>
            {current ? bytesToSize(current.byte_size) : "—"}
          </span>
          <span className="kpi-hint">canonical CSV on disk</span>
        </div>
      </div>

      <Card title="Observed demand" subtitle="Total units per day across the last 90 days (all series)">
        {demand.loading ? (
          <div className="skeleton tall" />
        ) : chartData.length === 0 ? (
          <EmptyState title="No observations available" />
        ) : (
          <>
            <div style={{ height: 240 }}>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                  <CartesianGrid stroke="#e6ecf3" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="#8296a8"
                    fontSize={11}
                    minTickGap={28}
                    tickFormatter={(value: string) => formatDate(value).slice(0, 6)}
                  />
                  <YAxis stroke="#8296a8" fontSize={11} width={48} />
                  <Tooltip
                    contentStyle={{ borderRadius: 8, border: "1px solid #dde5ee", fontSize: 12 }}
                    labelFormatter={(value) => formatDate(String(value))}
                    formatter={(value: number) => [`${formatNumber(value, 0)} units`, "Observed demand"]}
                  />
                  <Line type="monotone" dataKey="total" stroke="#0072b2" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="chart-insight">
              {chartData.length} days of history ending {formatDate(chartData[chartData.length - 1]?.date)}. The most
              recent week averages{" "}
              {formatNumber(
                chartData.slice(-7).reduce((sum, point) => sum + point.total, 0) / Math.max(chartData.slice(-7).length, 1),
                0,
              )}{" "}
              units per day across all series.
            </p>
          </>
        )}
      </Card>

      {quality ? (
        <Card title="Quality report" subtitle="Produced by the validator during import">
          <div className="grid grid-3">
            <div>
              <SmallCaps>Rows in / out</SmallCaps>
              <div>
                {formatNumber(quality.row_count_in, 0)} → {formatNumber(quality.row_count_out, 0)}
              </div>
            </div>
            <div>
              <SmallCaps>Duplicates summed</SmallCaps>
              <div>{formatNumber(quality.duplicate_rows_summed, 0)}</div>
            </div>
            <div>
              <SmallCaps>Missing dates filled</SmallCaps>
              <div>{formatNumber(quality.missing_dates_filled, 0)}</div>
            </div>
            <div>
              <SmallCaps>Rejected rows</SmallCaps>
              <div>{formatNumber(quality.rejected_rows, 0)}</div>
            </div>
            <div>
              <SmallCaps>Ignored columns</SmallCaps>
              <div>{quality.ignored_columns.length ? quality.ignored_columns.join(", ") : "none"}</div>
            </div>
            <div>
              <SmallCaps>Fingerprint</SmallCaps>
              <code style={{ fontSize: "0.72rem" }}>{current?.fingerprint_short}</code>
            </div>
          </div>
          {quality.warnings.length > 0 ? (
            <Notice tone="warn" title={`${quality.warnings.length} warning(s)`}>
              <ul className="plain" style={{ marginTop: "0.3rem" }}>
                {quality.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Notice>
          ) : (
            <Notice tone="ok">No ingestion warnings.</Notice>
          )}
        </Card>
      ) : null}

      <Card
        title="Series and on-hand stock"
        subtitle="On-hand is used only by reorder suggestions; it never influences the forecast"
        flush
      >
        <div className="table-wrap table-scroll" style={{ border: "none", borderRadius: 0 }} role="region" aria-label="Series and on-hand stock" tabIndex={0}>
          <table className="data">
            <caption>
              {series.length} store/item series. {canEdit ? "Edit on-hand stock inline." : "Read-only role."}
            </caption>
            <thead>
              <tr>
                <th scope="col">Store</th>
                <th scope="col">Item</th>
                <th scope="col" className="num">
                  On hand
                </th>
                <th scope="col">Updated</th>
                <th scope="col">Adjust</th>
              </tr>
            </thead>
            <tbody>
              {series.map((row) => (
                <tr key={row.id}>
                  <td>{row.store}</td>
                  <td>{row.item}</td>
                  <td className="num">{row.on_hand === null ? "missing" : formatNumber(row.on_hand, 0)}</td>
                  <td>{row.on_hand_updated_at ? formatDate(row.on_hand_updated_at) : "—"}</td>
                  <td>
                    {canEdit ? (
                      <div className="row" style={{ gap: "0.35rem" }}>
                        <input
                          type="number"
                          min={0}
                          aria-label={`On-hand quantity for ${row.store} ${row.item}`}
                          value={editing[row.id] ?? row.on_hand ?? 0}
                          onChange={(event) => setEditing({ ...editing, [row.id]: Number(event.target.value) })}
                          style={{ width: 110, minHeight: 32, padding: "0.2rem 0.4rem" }}
                        />
                        <button
                          className="button small"
                          type="button"
                          onClick={() => void saveOnHand(row)}
                          disabled={savingId === row.id || editing[row.id] === undefined}
                        >
                          {savingId === row.id ? "Saving…" : "Save"}
                        </button>
                      </div>
                    ) : (
                      <span style={{ color: "var(--ink-faint)", fontSize: "0.8rem" }}>read-only</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Version history" subtitle="Immutable imports, newest first" flush>
        <div className="table-wrap" style={{ border: "none", borderRadius: 0 }} role="region" aria-label="Version history" tabIndex={0}>
          <table className="data">
            <caption>Immutable imports, newest first. Re-importing identical content adds no version.</caption>
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">Fingerprint</th>
                <th scope="col" className="num">Rows</th>
                <th scope="col" className="num">Series</th>
                <th scope="col">Window</th>
                <th scope="col">Imported</th>
                <th scope="col">File</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((version) => (
                <tr key={version.id} className={version.id === current?.id ? "selected-row" : undefined}>
                  <td>v{version.version}</td>
                  <td>
                    <code style={{ fontSize: "0.72rem" }}>{version.fingerprint_short}</code>
                  </td>
                  <td className="num">{formatNumber(version.row_count, 0)}</td>
                  <td className="num">{formatNumber(version.series_count, 0)}</td>
                  <td>
                    {formatDate(version.date_min)} → {formatDate(version.date_max)}
                  </td>
                  <td>{formatDate(version.created_at)}</td>
                  <td>
                    <a href={`/api/v1/datasets/${dataset.id}/versions/${version.id}/download`}>CSV</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
