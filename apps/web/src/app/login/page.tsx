"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useSession } from "@/components/SessionProvider";
import { apiFetch, ApiError } from "@/lib/api";

const DEMO_ACCOUNTS = [
  { email: "demo@forecastops.example", password: "planning-demo-2024", role: "Owner" },
  { email: "analyst@forecastops.example", password: "analyst-demo-2024", role: "Analyst" },
  { email: "viewer@forecastops.example", password: "viewer-demo-2024", role: "Viewer" },
];

export default function LoginPage() {
  const router = useRouter();
  const { authenticated, loading, refresh } = useSession();
  const [email, setEmail] = useState("demo@forecastops.example");
  const [password, setPassword] = useState("planning-demo-2024");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && authenticated) router.replace("/dashboard");
  }, [authenticated, loading, router]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      await refresh();
      router.replace("/dashboard");
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "rate_limited") {
        setError("Too many sign-in attempts. Wait a minute, then try again.");
      } else {
        setError(caught instanceof Error ? caught.message : "Sign-in failed.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <section className="login-hero">
        <div>
          <span className="brand-sub" style={{ color: "#9fc0da" }}>
            ForecastOps
          </span>
          <h1>Forecast demand, compare honestly, plan stock.</h1>
        </div>
        <p>
          A leakage-aware forecasting workspace: a seasonal-naive baseline is always in the comparison, the
          evaluation window is chronological, and every reorder suggestion shows the arithmetic behind it.
        </p>
        <ul>
          <li>Validated CSV ingestion with content fingerprints</li>
          <li>Bounded background forecast jobs with retries and cancellation</li>
          <li>Holdout metrics, weak-series views and residual diagnostics</li>
          <li>Reorder suggestions as decision support — never automatic orders</li>
        </ul>
        <p style={{ fontSize: "0.78rem", color: "#9fc0da" }}>
          Every organization, store and number in this deployment is fictional and synthetic. Metrics are smoke
          results, not a real-world benchmark.
        </p>
      </section>

      <section className="login-panel">
        <form className="login-card" onSubmit={submit} aria-describedby={error ? "login-error" : undefined}>
          <div>
            <h2>Sign in</h2>
            <p style={{ color: "var(--ink-muted)", fontSize: "0.85rem", marginTop: "0.25rem" }}>
              Sessions are HTTP-only cookies scoped to this workspace.
            </p>
          </div>

          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>

          {error ? (
            <div className="notice danger" id="login-error" role="alert">
              {error}
            </div>
          ) : null}

          <button className="button primary" type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>

          <div className="demo-accounts">
            <strong style={{ color: "var(--ink-soft)" }}>Fictional demo accounts</strong>
            {DEMO_ACCOUNTS.map((account) => (
              <div className="demo-account-row" key={account.email}>
                <span>
                  {account.role}: <code>{account.email}</code>
                </span>
                <button
                  type="button"
                  className="button ghost small"
                  onClick={() => {
                    setEmail(account.email);
                    setPassword(account.password);
                  }}
                >
                  Use
                </button>
              </div>
            ))}
            <span>
              Second tenant for isolation checks: <code>cascade@forecastops.example</code> /{" "}
              <code>cascade-demo-2024</code>
            </span>
          </div>
        </form>
      </section>
    </div>
  );
}
