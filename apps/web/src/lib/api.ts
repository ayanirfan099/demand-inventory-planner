"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type ErrorBody = { error: { code: string; message: string; details?: Record<string, unknown>; request_id?: string } };

async function parseError(response: Response): Promise<ApiError> {
  let body: ErrorBody | null = null;
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    body = null;
  }
  const code = body?.error?.code ?? `http_${response.status}`;
  const message =
    body?.error?.message ??
    (response.status === 401
      ? "Your session expired. Sign in again."
      : "Something went wrong while contacting the API.");
  return new ApiError(response.status, code, message, body?.error?.details);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init.body && !(init.body instanceof FormData) ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [nonce, setNonce] = useState(0);
  const latest = useRef(0);

  const refetch = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    const requestId = ++latest.current;
    const controller = new AbortController();
    setLoading(true);
    apiFetch<T>(path, { signal: controller.signal })
      .then((result) => {
        if (requestId === latest.current) {
          setData(result);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        if (caught instanceof Error && caught.name === "AbortError") return;
        if (requestId === latest.current) {
          setError(caught instanceof ApiError ? caught : new ApiError(0, "network_error", "The API is unreachable."));
        }
      })
      .finally(() => {
        if (requestId === latest.current) setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, ...deps]);

  return { data, error, loading, refetch };
}

/** Poll a job until it reaches a terminal state. */
export function useJobPolling(jobId: number | null, onDone?: () => void) {
  const [job, setJob] = useState<{ id: number; status: string; progress: number; stage: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const body = await apiFetch<{ job: { id: number; status: string; progress: number; stage: string | null } }>(
          `/api/v1/forecast-jobs/${jobId}`,
        );
        if (cancelled) return;
        setJob(body.job);
        if (["succeeded", "failed", "cancelled"].includes(body.job.status)) {
          onDone?.();
          return;
        }
        timer = setTimeout(tick, 1500);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Polling failed.");
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return { job, error };
}
