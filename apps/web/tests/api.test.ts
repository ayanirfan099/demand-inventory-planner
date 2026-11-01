import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api";

const realFetch = globalThis.fetch;

function mockFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  const spy = vi.fn(handler);
  globalThis.fetch = spy as unknown as typeof fetch;
  return spy;
}

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("returns parsed JSON on success and sends credentials same-origin", async () => {
    const spy = mockFetch(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await expect(apiFetch<{ ok: boolean }>("/api/v1/auth/me")).resolves.toEqual({ ok: true });

    const init = spy.mock.calls[0][1];
    expect(init?.credentials).toBe("same-origin");
    expect((init?.headers as Record<string, string>)["content-type"]).toBeUndefined();
  });

  it("sends a JSON content type only when there is a JSON body", async () => {
    const spy = mockFetch(async () => new Response("{}", { status: 200 }));

    await apiFetch("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ email: "a@b.c" }) });
    await apiFetch("/api/v1/datasets/previews", { method: "POST", body: new FormData() });

    const jsonHeaders = spy.mock.calls[0][1]?.headers as Record<string, string>;
    const formHeaders = spy.mock.calls[1][1]?.headers as Record<string, string>;
    expect(jsonHeaders["content-type"]).toBe("application/json");
    // A FormData body must keep the browser-generated multipart boundary.
    expect(formHeaders["content-type"]).toBeUndefined();
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(async () => new Response(null, { status: 204 }));
    await expect(apiFetch("/api/v1/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("surfaces the API error code, message and details", async () => {
    mockFetch(
      async () =>
        new Response(
          JSON.stringify({
            error: { code: "invalid_dataset", message: "Missing columns: sales.", details: { missing: ["sales"] } },
          }),
          { status: 400 },
        ),
    );

    const failure = await apiFetch("/api/v1/datasets/imports").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(400);
    expect(apiError.code).toBe("invalid_dataset");
    expect(apiError.message).toBe("Missing columns: sales.");
    expect(apiError.details).toEqual({ missing: ["sales"] });
  });

  it("falls back to a transport-style code when the body is not JSON", async () => {
    mockFetch(async () => new Response("<html>gateway</html>", { status: 502 }));

    const failure = (await apiFetch("/api/v1/datasets").catch((error: unknown) => error)) as ApiError;
    expect(failure.code).toBe("http_502");
    expect(failure.message).toBe("Something went wrong while contacting the API.");
  });

  it("turns a bare 401 into a re-authenticate message", async () => {
    mockFetch(async () => new Response("", { status: 401 }));

    const failure = (await apiFetch("/api/v1/datasets").catch((error: unknown) => error)) as ApiError;
    expect(failure.status).toBe(401);
    expect(failure.code).toBe("http_401");
    expect(failure.message).toMatch(/session expired/i);
  });
});
