"use client";

import type { ReactNode } from "react";

import type { JobStatus } from "@/lib/types";

export function PageHead({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        {eyebrow ? (
          <div style={{ fontSize: "0.72rem", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-faint)", fontWeight: 650 }}>
            {eyebrow}
          </div>
        ) : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="row">{actions}</div> : null}
    </div>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  flush = false,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={`card ${flush ? "flush" : ""} ${className}`.trim()}>
      {title ? (
        <div className="card-head" style={flush ? { padding: "1.1rem 1.2rem 0" } : undefined}>
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {actions ? <div className="row">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Kpi({
  label,
  value,
  unit,
  hint,
  accent = false,
  title,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  accent?: boolean;
  title?: string;
}) {
  return (
    <div className={`kpi ${accent ? "accent" : ""}`.trim()} title={title}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">
        {value} {unit ? <small>{unit}</small> : null}
      </span>
      {hint ? <span className="kpi-hint">{hint}</span> : null}
    </div>
  );
}

export type Tone = "neutral" | "info" | "ok" | "warn" | "danger" | "teal";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

const JOB_TONES: Record<JobStatus, Tone> = {
  queued: "neutral",
  running: "info",
  succeeded: "ok",
  failed: "danger",
  cancelled: "warn",
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={`badge ${JOB_TONES[status] ?? "neutral"}`}>
      <span className="dot" aria-hidden="true" />
      {status}
    </span>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "danger" | "ok";
  title?: string;
  children: ReactNode;
}) {
  const role = tone === "danger" ? "alert" : undefined;
  return (
    <div className={`notice ${tone}`} role={role}>
      <div>
        {title ? <strong style={{ display: "block", marginBottom: "0.15rem" }}>{title}</strong> : null}
        {children}
      </div>
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="stack" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="skeleton" style={{ width: "30%" }} />
      <div className="skeleton tall" />
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function ErrorState({ title = "That did not work", children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="error-state" role="alert">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function Definition({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="definition">
      <summary>{label}</summary>
      <div style={{ color: "var(--ink-muted)" }}>{children}</div>
    </details>
  );
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="stack" style={{ gap: "0.35rem" }}>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Job progress"}
      >
        <div className="progress-fill" style={{ width: `${clamped}%` }} />
      </div>
      <span style={{ fontSize: "0.78rem", color: "var(--ink-muted)" }}>
        {label ? `${label} — ` : ""}
        {clamped}%
      </span>
    </div>
  );
}

export function SmallCaps({ children }: { children: ReactNode }) {
  return (
    <span style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--ink-faint)", fontWeight: 650 }}>
      {children}
    </span>
  );
}
