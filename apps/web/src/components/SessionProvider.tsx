"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type { SessionResponse } from "@/lib/types";

interface SessionState {
  session: SessionResponse | null;
  loading: boolean;
  error: string | null;
  authenticated: boolean;
  refresh: () => Promise<void>;
  switchOrg: (orgId: number) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<SessionResponse>("/api/v1/auth/me");
      setSession(data);
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setSession(null);
        setError(null);
      } else {
        setError(caught instanceof Error ? caught.message : "Could not reach the API.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const switchOrg = useCallback(async (orgId: number) => {
    const data = await apiFetch<SessionResponse>("/api/v1/auth/switch-org", {
      method: "POST",
      body: JSON.stringify({ org_id: orgId }),
    });
    setSession(data);
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch<void>("/api/v1/auth/logout", { method: "POST" });
    } finally {
      setSession(null);
    }
  }, []);

  const value = useMemo<SessionState>(
    () => ({
      session,
      loading,
      error,
      authenticated: Boolean(session),
      refresh,
      switchOrg,
      logout,
    }),
    [session, loading, error, refresh, switchOrg, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside SessionProvider");
  return context;
}
