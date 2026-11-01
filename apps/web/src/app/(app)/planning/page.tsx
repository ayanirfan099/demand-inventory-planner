"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

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
import { formatNumber, formatPercent, formatUnits } from "@/lib/format";
import type { DatasetSummary, InventoryPolicy, Suggestion } from "@/lib/types";

interface PolicyDetailResponse {
  policy: InventoryPolicy;
  suggestions: Suggestion[];
  formula: { text: string; notes: string[] };
}

export default function PlanningPage() {
  const { session } = useSession();
  const datasets = useApi<{ datasets: DatasetSummary[] }>("/api/v1/datasets");
  const policies = useApi<{ policies: InventoryPolicy[] }>("/api/v1/inventory-policies");

  const [selectedPolicyId, setSelectedPolicyId] = useState<number | null>(null);
  const policyDetail = useApi<PolicyDetailResponse>(
    selectedPolicyId ? `/api/v1/inventory-policies/${selectedPolicyId}` : null,
  );

  const [form, setForm] = useState({
    dataset_id: 0,
    name: "",
    lead_time_days: 14,
    review_period_days: 7,
    service_level: 0.95,
    min_order_qty: 0,
    pack_size: 1,
  });
  const [creating, setCreating] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latestRun, setLatestRun] = useState<{ run_id: number; label: string } | null>(null);

  const canWrite = session?.role === "owner" || session?.role === "analyst";
  const datasetList = useMemo(() => datasets.data?.datasets ?? [], [datasets.data]);
  const policyList = policies.data?.policies ?? [];

  useEffect(() => {
    if (!form.dataset_id && datasetList.length > 0) {
      setForm((current) => ({ ...current, dataset_id: datasetList[0].id }));
    }
  }, [datasetList, form.dataset_id]);

  useEffect(() => {
    if (!selectedPolicyId) return;
    setLatestRun(null);
    apiFetch<{ run_id: number; label: string }>(`/api/v1/inventory-policies/${selectedPolicyId}/latest-run`)
      .then(setLatestRun)
      .catch(() => setLatestRun(null));
  }, [selectedPolicyId]);

  const createPolicy = async (event: React.FormEvent) => {
    event.preventDefault();
    setCreating(true);
    setError(null);
    setMessage(null);
    try {
      const body = await apiFetch<{ policy: InventoryPolicy }>("/api/v1/inventory-policies", {
        method: "POST",
        body: JSON.stringify(form),
      });
      setMessage(`Policy "${body.policy.name}" created.`);
      setSelectedPolicyId(body.policy.id);
      setForm((current) => ({ ...current, name: "" }));
      policies.refetch();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not create the policy.");
    } finally {
      setCreating(false);
    }
  };

  const generate = async () => {
    if (!selectedPolicyId || !latestRun) return;
    setGenerating(true);
    setError(null);
    setMessage(null);
    try {
      const body = await apiFetch<{ summary: { series: number; series_with_order: number; total_units: number } }>(
        `/api/v1/inventory-policies/${selectedPolicyId}/suggestions`,
        { method: "POST", body: JSON.stringify({ run_id: latestRun.run_id }) },
      );
      setMessage(
        `Generated ${body.summary.series} suggestions · ${body.summary.series_with_order} series below reorder point · ${body.summary.total_units} units total.`,
      );
      policyDetail.refetch();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not generate suggestions.");
    } finally {
      setGenerating(false);
    }
  };

  const updateStatus = async (suggestionId: number, status: "acknowledged" | "dismissed") => {
    setError(null);
    try {
      await apiFetch(`/api/v1/inventory-suggestions/${suggestionId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      policyDetail.refetch();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update the suggestion.");
    }
  };

  if (datasets.loading || policies.loading) return <Loading label="Loading planning workspace" />;
  if (datasets.error) return <ErrorState title="Planning unavailable">{datasets.error.message}</ErrorState>;

  if (datasetList.length === 0) {
    return (
      <>
        <PageHead title="Inventory planning" description="Reorder decision support built on a forecast run." />
        <EmptyState title="No dataset yet">
          <Link className="button" href="/upload">
            Import data
          </Link>
        </EmptyState>
      </>
    );
  }

  const selectedSuggestions = policyDetail.data?.suggestions ?? [];
  const orderRows = selectedSuggestions.filter((row) => row.suggested_qty > 0);
  const totalUnits = orderRows.reduce((sum, row) => sum + row.suggested_qty, 0);

  return (
    <>
      <PageHead
        eyebrow="Planning"
        title="Reorder decision support"
        description="A documented periodic-review policy turns a forecast into quantity suggestions. Nothing is ordered automatically, and every suggestion stores the inputs it was computed from."
      />

      <Notice tone="warn" title="Decision support, not purchasing">
        Suggestions assume a fixed lead time, ignore supplier constraints and price breaks, and cannot recover demand
        lost to stockouts. Confirm on-hand stock before acting.
      </Notice>

      {message ? <Notice tone="ok">{message}</Notice> : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}

      <div className="split-main">
        <div className="stack">
          <Card
            title="Policies"
            subtitle="One policy per dataset and name"
            actions={
              <select
                aria-label="Select policy"
                value={selectedPolicyId ?? ""}
                onChange={(event) => setSelectedPolicyId(event.target.value ? Number(event.target.value) : null)}
                style={{ minWidth: 220 }}
              >
                <option value="">Select a policy…</option>
                {policyList.map((policy) => (
                  <option key={policy.id} value={policy.id}>
                    {policy.name} (dataset #{policy.dataset_id})
                  </option>
                ))}
              </select>
            }
          >
            {policyList.length === 0 ? (
              <EmptyState title="No policies yet">Create one with the form on the right.</EmptyState>
            ) : (
              <div className="stack" style={{ gap: "0.5rem" }}>
                {policyList.map((policy) => (
                  <button
                    key={policy.id}
                    type="button"
                    className="card"
                    onClick={() => setSelectedPolicyId(policy.id)}
                    aria-pressed={selectedPolicyId === policy.id}
                    style={{
                      textAlign: "left",
                      cursor: "pointer",
                      borderColor: selectedPolicyId === policy.id ? "var(--teal-500)" : "var(--line)",
                      background: selectedPolicyId === policy.id ? "var(--teal-100)" : "var(--surface)",
                      padding: "0.8rem 0.9rem",
                    }}
                  >
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <strong>{policy.name}</strong>
                      <Badge tone="neutral">window {policy.planning_window_days}d</Badge>
                    </div>
                    <span style={{ fontSize: "0.8rem", color: "var(--ink-muted)" }}>
                      lead {policy.lead_time_days}d · review {policy.review_period_days}d · service{" "}
                      {formatPercent(policy.service_level, 1)} · MOQ {policy.min_order_qty} · pack {policy.pack_size}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Card>

          {selectedPolicyId ? (
            <Card
              title={policyDetail.data?.policy.name ?? "Policy detail"}
              subtitle="Formula, assumptions and generated suggestions"
              actions={
                <>
                  {latestRun ? (
                    <Badge tone="info">latest run #{latestRun.run_id}</Badge>
                  ) : (
                    <Badge tone="warn">no completed run</Badge>
                  )}
                  <button
                    className="button primary small"
                    type="button"
                    onClick={() => void generate()}
                    disabled={!canWrite || !latestRun || generating || !policyDetail.data}
                  >
                    {generating ? "Computing…" : "Generate suggestions"}
                  </button>
                </>
              }
            >
              {policyDetail.loading ? (
                <div className="skeleton tall" />
              ) : policyDetail.error ? (
                <ErrorState>{policyDetail.error.message}</ErrorState>
              ) : policyDetail.data ? (
                <>
                  <SmallCaps>Formula</SmallCaps>
                  <pre className="formula">{policyDetail.data.formula.text}</pre>
                  <ul className="plain">
                    {policyDetail.data.formula.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>

                  {selectedSuggestions.length === 0 ? (
                    <EmptyState title="No suggestions yet">
                      {latestRun
                        ? "Generate suggestions from the latest completed run."
                        : "Run a forecast for this dataset first."}
                    </EmptyState>
                  ) : (
                    <>
                      <div className="grid grid-3" style={{ gap: "0.5rem" }}>
                        <div className="kpi" style={{ padding: "0.6rem 0.75rem" }}>
                          <span className="kpi-label">Series below reorder point</span>
                          <span className="kpi-value" style={{ fontSize: "1.1rem" }}>
                            {orderRows.length}
                            <small> / {selectedSuggestions.length}</small>
                          </span>
                        </div>
                        <div className="kpi" style={{ padding: "0.6rem 0.75rem" }}>
                          <span className="kpi-label">Units to order</span>
                          <span className="kpi-value" style={{ fontSize: "1.1rem" }}>
                            {formatUnits(totalUnits)}
                          </span>
                        </div>
                        <div className="kpi" style={{ padding: "0.6rem 0.75rem" }}>
                          <span className="kpi-label">Open</span>
                          <span className="kpi-value" style={{ fontSize: "1.1rem" }}>
                            {selectedSuggestions.filter((row) => row.status === "open").length}
                          </span>
                        </div>
                      </div>

                      <div className="table-wrap table-scroll">
                        <table className="data">
                          <caption>
                            Suggestions sorted by newest first. Quantities are rounded up to whole packs; the raw value
                            is shown for audit.
                          </caption>
                          <thead>
                            <tr>
                              <th scope="col">Series</th>
                              <th scope="col" className="num">On hand</th>
                              <th scope="col" className="num">Forecast demand</th>
                              <th scope="col" className="num">Safety stock</th>
                              <th scope="col" className="num">Reorder point</th>
                              <th scope="col" className="num">Projected</th>
                              <th scope="col" className="num">Order</th>
                              <th scope="col">Status</th>
                              <th scope="col" />
                            </tr>
                          </thead>
                          <tbody>
                            {selectedSuggestions.map((row) => (
                              <tr key={row.id}>
                                <td>
                                  {row.item} @ {row.store}
                                </td>
                                <td className="num">{formatNumber(row.on_hand, 0)}</td>
                                <td className="num">{formatNumber(row.forecast_demand, 0)}</td>
                                <td className="num">{formatNumber(row.safety_stock, 1)}</td>
                                <td className="num">{formatNumber(row.reorder_point, 0)}</td>
                                <td className="num" style={{ color: row.projected_on_hand < 0 ? "var(--red-600)" : undefined }}>
                                  {formatNumber(row.projected_on_hand, 0)}
                                </td>
                                <td className="num">
                                  <strong>{row.suggested_qty > 0 ? formatNumber(row.suggested_qty, 0) : "0"}</strong>
                                  {row.suggested_qty > 0 ? (
                                    <div style={{ fontSize: "0.7rem", color: "var(--ink-faint)" }}>
                                      raw {formatNumber(row.suggested_qty_raw)}
                                    </div>
                                  ) : null}
                                </td>
                                <td>
                                  <Badge
                                    tone={row.status === "open" ? "warn" : row.status === "acknowledged" ? "ok" : "neutral"}
                                  >
                                    {row.status}
                                  </Badge>
                                </td>
                                <td>
                                  {canWrite && row.status === "open" ? (
                                    <div className="row" style={{ gap: "0.25rem" }}>
                                      <button
                                        className="button small"
                                        type="button"
                                        onClick={() => void updateStatus(row.id, "acknowledged")}
                                      >
                                        Ack
                                      </button>
                                      <button
                                        className="button small ghost"
                                        type="button"
                                        onClick={() => void updateStatus(row.id, "dismissed")}
                                      >
                                        Dismiss
                                      </button>
                                    </div>
                                  ) : null}
                                  {row.assumptions ? (
                                    <details className="definition" style={{ marginTop: "0.35rem" }}>
                                      <summary>Assumptions</summary>
                                      <div className="assumption-grid" style={{ gridTemplateColumns: "1fr" }}>
                                        <div>
                                          <span>service factor z</span>
                                          <span>{row.assumptions.service_factor_z}</span>
                                        </div>
                                        <div>
                                          <span>residual σ (daily)</span>
                                          <span>{row.assumptions.residual_sigma_daily}</span>
                                        </div>
                                        <div>
                                          <span>window</span>
                                          <span>{row.assumptions.planning_window_days}d</span>
                                        </div>
                                        <div>
                                          <span>extrapolated days</span>
                                          <span>{row.assumptions.extrapolated_days_beyond_horizon}</span>
                                        </div>
                                        <div>
                                          <span>on-hand source</span>
                                          <span>{row.assumptions.on_hand_source}</span>
                                        </div>
                                      </div>
                                      <p style={{ marginTop: "0.4rem", color: "var(--ink-muted)" }}>
                                        Not modelled: {row.assumptions.not_modelled.join(", ")}.
                                      </p>
                                    </details>
                                  ) : null}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  )}
                </>
              ) : null}
            </Card>
          ) : null}
        </div>

        <div className="stack">
          <Card title="New policy" subtitle="Explicit inputs, no hidden defaults">
            {!canWrite ? <Notice tone="info">Read-only role: ask an analyst to configure a policy.</Notice> : null}
            <form className="stack" onSubmit={createPolicy}>
              <div className="field">
                <label htmlFor="policy-dataset">Dataset</label>
                <select
                  id="policy-dataset"
                  value={form.dataset_id}
                  onChange={(event) => setForm({ ...form, dataset_id: Number(event.target.value) })}
                  disabled={!canWrite}
                >
                  {datasetList.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="policy-name">Policy name</label>
                <input
                  id="policy-name"
                  type="text"
                  value={form.name}
                  maxLength={160}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  required
                  disabled={!canWrite}
                />
              </div>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="lead-time">Lead time (days)</label>
                  <input
                    id="lead-time"
                    type="number"
                    min={0}
                    max={365}
                    value={form.lead_time_days}
                    onChange={(event) => setForm({ ...form, lead_time_days: Number(event.target.value) })}
                    disabled={!canWrite}
                  />
                </div>
                <div className="field">
                  <label htmlFor="review-period">Review period (days)</label>
                  <input
                    id="review-period"
                    type="number"
                    min={1}
                    max={180}
                    value={form.review_period_days}
                    onChange={(event) => setForm({ ...form, review_period_days: Number(event.target.value) })}
                    disabled={!canWrite}
                  />
                </div>
                <div className="field">
                  <label htmlFor="service-level">Service level</label>
                  <input
                    id="service-level"
                    type="number"
                    min={0.51}
                    max={0.998}
                    step={0.005}
                    value={form.service_level}
                    onChange={(event) => setForm({ ...form, service_level: Number(event.target.value) })}
                    disabled={!canWrite}
                  />
                  <span className="help">0.95 → z ≈ 1.645 · planning input, not a guarantee</span>
                </div>
                <div className="field">
                  <label htmlFor="moq">Minimum order quantity</label>
                  <input
                    id="moq"
                    type="number"
                    min={0}
                    value={form.min_order_qty}
                    onChange={(event) => setForm({ ...form, min_order_qty: Number(event.target.value) })}
                    disabled={!canWrite}
                  />
                </div>
                <div className="field">
                  <label htmlFor="pack-size">Pack size</label>
                  <input
                    id="pack-size"
                    type="number"
                    min={1}
                    value={form.pack_size}
                    onChange={(event) => setForm({ ...form, pack_size: Number(event.target.value) })}
                    disabled={!canWrite}
                  />
                  <span className="help">orders round up to whole packs</span>
                </div>
              </div>
              <button className="button primary" type="submit" disabled={!canWrite || creating || !form.name}>
                {creating ? "Creating…" : "Create policy"}
              </button>
            </form>
          </Card>

          <Card title="How quantities are computed" subtitle="Same formula for every series">
            <pre className="formula">{`W         = lead_time_days + review_period_days
demand    = Σ forecast over W
safety    = z(service_level) × σ_holdout × √W
reorder   = demand + safety
shortage  = max(0, reorder − on_hand)
order     = ceil(max(shortage, MOQ) / pack) × pack`}</pre>
            <ul className="plain">
              <li>σ comes from the selected model&apos;s holdout residuals for that series.</li>
              <li>Adding to the order when the forecast horizon is shorter than W is flagged per suggestion.</li>
              <li>Zero-demand series produce a zero order — never a default quantity.</li>
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
