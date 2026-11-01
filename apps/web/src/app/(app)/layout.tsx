"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Shell } from "@/components/Shell";
import { useSession } from "@/components/SessionProvider";
import { ErrorState, Loading } from "@/components/ui";

function Guard({ children }: { children: React.ReactNode }) {
  const { loading, authenticated, error, refresh } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !authenticated) {
      router.replace("/login");
    }
  }, [loading, authenticated, router]);

  if (loading) {
    return (
      <main className="content" style={{ paddingTop: "3rem" }}>
        <Loading label="Checking your session" />
        <noscript>
          <p className="chart-insight">
            ForecastOps needs JavaScript: the planning views load your data after the session is
            confirmed. Enable JavaScript to sign in. The REST API at <code>/api/v1</code> works
            without it.
          </p>
        </noscript>
      </main>
    );
  }

  if (error) {
    return (
      <main className="content" style={{ paddingTop: "3rem" }}>
        <ErrorState title="The API is not responding">
          {error}
          <button className="button" type="button" onClick={() => void refresh()} style={{ marginTop: "0.5rem" }}>
            Retry
          </button>
        </ErrorState>
      </main>
    );
  }

  if (!authenticated) return null;

  return <Shell>{children}</Shell>;
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <Guard>{children}</Guard>;
}
