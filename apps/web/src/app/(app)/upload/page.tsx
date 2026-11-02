"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { useSession } from "@/components/SessionProvider";
import {
  Badge,
  Card,
  ErrorState,
  Notice,
  PageHead,
  SmallCaps,
} from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import { bytesToSize, formatDate, formatNumber, formatPercent } from "@/lib/format";
import type { DatasetSummary, PreviewResponse } from "@/lib/types";

const REQUIRED_COLUMNS = ["date", "store", "item", "sales"];
const OPTIONAL_COLUMNS = ["on_hand"];

export default function UploadPage() {
  const { session } = useSession();
  const fileInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState<{ dataset: DatasetSummary; message: string } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const [syntheticName, setSyntheticName] = useState("Synthetic demo demand");
  const [syntheticDays, setSyntheticDays] = useState(365);
  const [syntheticSeed, setSyntheticSeed] = useState(20240517);
  const [generating, setGenerating] = useState(false);
  const [syntheticResult, setSyntheticResult] = useState<string | null>(null);

  const canWrite = session?.role === "owner" || session?.role === "analyst";

  const handleFile = async (file: File) => {
    setUploading(true);
    setPreviewError(null);
    setImported(null);
    setImportError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const body = await apiFetch<PreviewResponse>("/api/v1/datasets/previews", { method: "POST", body: form });
      setPreview(body);
      setName(file.name.replace(/\.csv$/i, "").slice(0, 80));
    } catch (caught) {
      setPreview(null);
      const message =
        caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : "Upload failed.";
      setPreviewError(message);
    } finally {
      setUploading(false);
    }
  };

  const confirmImport = async () => {
    if (!preview) return;
    setImporting(true);
    setImportError(null);
    try {
      const body = await apiFetch<{ dataset: DatasetSummary; message: string }>("/api/v1/datasets/imports", {
        method: "POST",
        body: JSON.stringify({
          preview_id: preview.preview_id,
          name: name || "Imported dataset",
          description: description || null,
        }),
      });
      setImported({ dataset: body.dataset, message: body.message });
      setPreview(null);
    } catch (caught) {
      setImportError(caught instanceof ApiError ? caught.message : "Import failed.");
    } finally {
      setImporting(false);
    }
  };

  const generateSynthetic = async (event: React.FormEvent) => {
    event.preventDefault();
    setGenerating(true);
    setSyntheticResult(null);
    try {
      const body = await apiFetch<{ dataset: DatasetSummary; created_new_version: boolean }>(
        "/api/v1/datasets/synthetic",
        {
          method: "POST",
          body: JSON.stringify({ name: syntheticName, days: syntheticDays, seed: syntheticSeed }),
        },
      );
      setSyntheticResult(
        `${body.dataset.name} v${body.dataset.current_version?.version} — ${body.created_new_version ? "new version imported" : "identical content already imported"}.`,
      );
    } catch (caught) {
      setSyntheticResult(caught instanceof ApiError ? caught.message : "Generation failed.");
    } finally {
      setGenerating(false);
    }
  };

  if (!canWrite) {
    return (
      <>
        <PageHead title="Import data" description="CSV ingestion with validation and a preview step." />
        <Notice tone="info" title="Read-only role">
          Your role is <strong>{session?.role}</strong>. Ask an owner or analyst in this workspace to import data.
        </Notice>
      </>
    );
  }

  return (
    <>
      <PageHead
        eyebrow="Data ingestion"
        title="Import demand data"
        description="Upload a CSV, review exactly what the validator will do with it, then confirm. Files are never executed and the original filename is never used as a storage path."
        actions={
          <Link className="button" href="/datasets">
            View datasets
          </Link>
        }
      />

      <Card title="1. Choose a CSV" subtitle="Bounded upload — validated before anything is persisted">
        <div
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const file = event.dataTransfer.files?.[0];
            if (file) void handleFile(file);
          }}
          style={{
            border: "2px dashed var(--line-strong)",
            borderRadius: "var(--radius)",
            padding: "1.5rem",
            textAlign: "center",
            background: "var(--surface-muted)",
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
            alignItems: "center",
          }}
        >
          <p style={{ fontWeight: 600 }}>Drop a CSV here, or choose a file</p>
          <p style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>
            Required columns: <code>{REQUIRED_COLUMNS.join(", ")}</code>. Optional:{" "}
            <code>{OPTIONAL_COLUMNS.join(", ")}</code>. Max 5 MB and 200,000 rows.
          </p>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            aria-label="Choose a CSV file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleFile(file);
            }}
            style={{ maxWidth: 360 }}
          />
          {uploading ? <SmallCaps>Validating…</SmallCaps> : null}
        </div>

        {previewError ? (
          <ErrorState title="That file could not be imported">
            {previewError}
            <span style={{ fontSize: "0.8rem" }}>
              Fix the rows described above and try again. Nothing was saved.
            </span>
          </ErrorState>
        ) : null}
      </Card>

      {imported ? (
        <Notice tone="ok" title="Import complete">
          {imported.message}{" "}
          <Link href={`/datasets/${imported.dataset.id}`}>View {imported.dataset.name}</Link>
        </Notice>
      ) : null}

      {preview ? (
        <>
          <Card
            title="2. Review the validation report"
            subtitle={`${preview.original_filename} · fingerprint ${preview.fingerprint.slice(0, 22)}…`}
            actions={<Badge tone="ok">Valid</Badge>}
          >
            <div className="grid grid-kpi">
              <div className="kpi">
                <span className="kpi-label">Rows accepted</span>
                <span className="kpi-value">{formatNumber(preview.quality.row_count_out, 0)}</span>
                <span className="kpi-hint">
                  from {formatNumber(preview.quality.row_count_in, 0)} input rows ·{" "}
                  {formatNumber(preview.quality.rejected_rows, 0)} rejected
                </span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Series</span>
                <span className="kpi-value">{formatNumber(preview.quality.series_count, 0)}</span>
                <span className="kpi-hint">store × item combinations</span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Date range</span>
                <span className="kpi-value" style={{ fontSize: "1rem" }}>
                  {formatDate(preview.quality.date_min)} → {formatDate(preview.quality.date_max)}
                </span>
                <span className="kpi-hint">dates normalised to calendar days</span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Zero-demand days</span>
                <span className="kpi-value">
                  {formatPercent(
                    preview.quality.row_count_out ? preview.quality.zero_demand_days / preview.quality.row_count_out : 0,
                  )}
                </span>
                <span className="kpi-hint">
                  duplicates summed: {formatNumber(preview.quality.duplicate_rows_summed, 0)}
                </span>
              </div>
            </div>

            {preview.quality.warnings.length > 0 ? (
              <Notice tone="warn" title={`${preview.quality.warnings.length} warning(s)`}>
                <ul className="plain" style={{ marginTop: "0.3rem" }}>
                  {preview.quality.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </Notice>
            ) : (
              <Notice tone="ok">No data-quality warnings for this file.</Notice>
            )}

            <div className="grid grid-2">
              <div className="stack" style={{ gap: "0.4rem" }}>
                <SmallCaps>Import policy</SmallCaps>
                <ul className="plain">
                  <li>{preview.policy.duplicates}</li>
                  <li>{preview.policy.missing_dates}</li>
                  <li>{preview.policy.negative_sales}</li>
                  <li>{preview.policy.dates}</li>
                </ul>
              </div>
              <div className="stack" style={{ gap: "0.4rem" }}>
                <SmallCaps>Limits</SmallCaps>
                <ul className="plain">
                  <li>Max {formatNumber(preview.limits.max_rows, 0)} rows</li>
                  <li>Max {formatNumber(preview.limits.max_series, 0)} series</li>
                  <li>Max {bytesToSize(preview.limits.max_bytes)} per upload</li>
                  <li>Preview expires after 30 minutes</li>
                </ul>
              </div>
            </div>

            <div className="table-wrap table-scroll" role="region" aria-label="Accepted rows preview" tabIndex={0}>
              <table className="data">
                <caption>First {preview.sample_rows.length} accepted rows (already normalised).</caption>
                <thead>
                  <tr>
                    {preview.columns.map((column) => (
                      <th scope="col" key={column}>
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.map((row, index) => (
                    <tr key={index}>
                      {preview.columns.map((column) => (
                        <td key={column} className={column === "sales" || column === "on_hand" ? "num" : undefined}>
                          {String(row[column] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {preview.quality.rejected_examples.length > 0 ? (
              <Notice tone="danger" title="Rows that will be rejected">
                <ul className="plain" style={{ marginTop: "0.3rem" }}>
                  {preview.quality.rejected_examples.map((example) => (
                    <li key={example.row_number}>
                      CSV row {example.row_number}: {example.reason}
                    </li>
                  ))}
                </ul>
              </Notice>
            ) : null}
          </Card>

          <Card title="3. Name and import" subtitle="Content-derived fingerprint deduplicates identical uploads">
            <div className="form-grid">
              <div className="field">
                <label htmlFor="dataset-name">Dataset name</label>
                <input
                  id="dataset-name"
                  type="text"
                  value={name}
                  maxLength={160}
                  onChange={(event) => setName(event.target.value)}
                  required
                />
                <span className="help">Re-using a name adds a new version to that dataset.</span>
              </div>
              <div className="field">
                <label htmlFor="dataset-description">Description (optional)</label>
                <input
                  id="dataset-description"
                  type="text"
                  value={description}
                  maxLength={2000}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </div>
            </div>
            {importError ? <ErrorState>{importError}</ErrorState> : null}
            <div className="row">
              <button className="button primary" type="button" onClick={() => void confirmImport()} disabled={importing || !name}>
                {importing ? "Importing…" : "Confirm import"}
              </button>
              <button className="button" type="button" onClick={() => setPreview(null)} disabled={importing}>
                Discard preview
              </button>
              <span className="help">Saving stores a canonical copy and a full quality report.</span>
            </div>
          </Card>
        </>
      ) : null}

      <Card
        title="Or generate deterministic synthetic data"
        subtitle="Seeded generator — useful for exploring the app without any real data"
      >
        <form className="form-grid" onSubmit={generateSynthetic}>
          <div className="field">
            <label htmlFor="synthetic-name">Synthetic dataset name</label>
            <input
              id="synthetic-name"
              type="text"
              value={syntheticName}
              onChange={(event) => setSyntheticName(event.target.value)}
              maxLength={160}
            />
          </div>
          <div className="field">
            <label htmlFor="synthetic-days">Days</label>
            <input
              id="synthetic-days"
              type="number"
              min={60}
              max={730}
              value={syntheticDays}
              onChange={(event) => setSyntheticDays(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="synthetic-seed">Seed</label>
            <input
              id="synthetic-seed"
              type="number"
              min={0}
              value={syntheticSeed}
              onChange={(event) => setSyntheticSeed(Number(event.target.value))}
            />
            <span className="help">Same seed → identical dataset</span>
          </div>
          <div className="field" style={{ justifyContent: "flex-end" }}>
            <button className="button teal" type="submit" disabled={generating}>
              {generating ? "Generating…" : "Generate dataset"}
            </button>
          </div>
        </form>
        {syntheticResult ? <Notice tone="info">{syntheticResult}</Notice> : null}
        <Notice tone="warn" title="Synthetic data is not evidence">
          Metrics computed on generated demand demonstrate the software pipeline only. Never present them as
          real-world forecasting performance.
        </Notice>
      </Card>

      <Card title="Data contract" subtitle="What the validator expects">
        <div className="grid grid-2">
          <div>
            <SmallCaps>Columns</SmallCaps>
            <pre className="formula">{`date,store,item,sales,on_hand
2025-01-01,north-dock,coffee-beans,42,310`}</pre>
          </div>
          <ul className="plain">
            <li>
              <strong>date</strong> — ISO date; any time component is dropped.
            </li>
            <li>
              <strong>store</strong>, <strong>item</strong> — non-empty identifiers (max 120 chars).
            </li>
            <li>
              <strong>sales</strong> — non-negative daily units; negatives are rejected (returns are not modelled).
            </li>
            <li>
              <strong>on_hand</strong> — optional latest physical stock, used only by reorder suggestions.
            </li>
          </ul>
        </div>
      </Card>
    </>
  );
}
