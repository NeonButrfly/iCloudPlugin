import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildHealthPayload,
  buildOriginUrl,
  fetchOriginJson,
  getAuthMode,
  hasValidWorkerApiToken,
  maybeHandleNonMcpRequest,
  proxyDownload,
  timingSafeEqualBytes,
  unauthorizedResponse,
  withWorkerDownloadUrl,
} from "../src/runtime";

type Env = {
  ORIGIN_BASE_URL: string;
  ORIGIN_API_TOKEN: string;
  WORKER_API_TOKEN?: string;
  MCP_ROUTE?: string;
  DOWNLOAD_ROUTE_PREFIX?: string;
  HEALTH_ROUTE?: string;
};

const baseEnv: Env = {
  ORIGIN_BASE_URL: "https://origin.example.test",
  ORIGIN_API_TOKEN: "origin-secret",
  WORKER_API_TOKEN: "worker-secret",
  MCP_ROUTE: "/mcp",
  DOWNLOAD_ROUTE_PREFIX: "/download",
  HEALTH_ROUTE: "/healthz",
};
const originalFetch = globalThis.fetch;

describe("remote MCP worker helpers", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("builds normalized origin URLs", () => {
    expect(buildOriginUrl("https://origin.example.test", "/files/5")).toBe(
      "https://origin.example.test/files/5",
    );
    expect(buildOriginUrl("https://origin.example.test/api/", "files/5")).toBe(
      "https://origin.example.test/api/files/5",
    );
  });

  it("reports auth mode from worker token presence", () => {
    expect(getAuthMode(baseEnv)).toBe("worker-api-token");
    expect(
      getAuthMode({
        ...baseEnv,
        WORKER_API_TOKEN: "   ",
      }),
    ).toBe("origin-only");
  });

  it("compares bytes safely in fallback mode", () => {
    expect(timingSafeEqualBytes(new Uint8Array([1, 2]), new Uint8Array([1, 2]))).toBe(true);
    expect(timingSafeEqualBytes(new Uint8Array([1, 2]), new Uint8Array([1, 3]))).toBe(false);
    expect(timingSafeEqualBytes(new Uint8Array([1, 2]), new Uint8Array([1, 2, 3]))).toBe(false);
  });

  it("accepts requests when no worker token is configured", async () => {
    const request = new Request("https://worker.example.test/mcp");
    const result = await hasValidWorkerApiToken(request, {
      ...baseEnv,
      WORKER_API_TOKEN: "",
    });
    expect(result).toBe(true);
  });

  it("rejects missing bearer auth when worker token is required", async () => {
    const request = new Request("https://worker.example.test/mcp");
    await expect(hasValidWorkerApiToken(request, baseEnv)).resolves.toBe(false);
  });

  it("accepts a matching bearer token even without subtle.timingSafeEqual", async () => {
    const subtle = crypto.subtle as SubtleCrypto & {
      timingSafeEqual?: (a: BufferSource, b: BufferSource) => boolean;
    };
    const originalTimingSafeEqual = subtle.timingSafeEqual;
    subtle.timingSafeEqual = undefined;

    try {
      const request = new Request("https://worker.example.test/mcp", {
        headers: {
          Authorization: "Bearer worker-secret",
        },
      });
      await expect(hasValidWorkerApiToken(request, baseEnv)).resolves.toBe(true);
    } finally {
      subtle.timingSafeEqual = originalTimingSafeEqual;
    }
  });

  it("builds non-secret health payloads", () => {
    const request = new Request("https://worker.example.test/healthz");
    expect(buildHealthPayload(baseEnv, request)).toEqual({
      status: "ok",
      name: "iCloudPlugin Remote MCP",
      version: "0.1.0",
      auth_mode: "worker-api-token",
      mcp_route: "https://worker.example.test/mcp",
      download_route_prefix: "https://worker.example.test/download",
      health_route: "https://worker.example.test/healthz",
      has_origin_base_url: true,
      has_origin_api_token: true,
    });
  });

  it("adds worker download URLs when source download metadata is present", () => {
    const request = new Request("https://worker.example.test/mcp");
    const enriched = withWorkerDownloadUrl(
      {
        file_id: 42,
        download_path: "/files/42/source/download",
      },
      request,
      baseEnv,
    );
    expect(enriched).toMatchObject({
      file_id: 42,
      worker_download_url: "https://worker.example.test/download/42",
    });
  });

  it("returns a standard unauthorized payload", async () => {
    const response = unauthorizedResponse();
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({
      error: "unauthorized",
    });
  });

  it("forwards origin auth for JSON requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, value: 7 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    const payload = await fetchOriginJson(baseEnv, "/files/7");
    expect(payload).toEqual({ ok: true, value: 7 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://origin.example.test/files/7");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer origin-secret");
    expect(new Headers(init.headers).get("Accept")).toBe("application/json");
  });

  it("proxies file downloads through the Worker", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("payload-bytes", {
        status: 200,
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Disposition": "attachment; filename=test.bin",
        },
      }),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    const response = await proxyDownload(
      new Request("https://worker.example.test/download/42"),
      baseEnv,
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("payload-bytes");
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
    expect(response.headers.get("Content-Disposition")).toBe(
      "attachment; filename=test.bin",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://origin.example.test/files/42/source/download");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer origin-secret");
  });
});

describe("remote MCP worker route guards", () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("serves health metadata at /healthz without auth", async () => {
    const response = await maybeHandleNonMcpRequest(
      new Request("https://worker.example.test/healthz"),
      baseEnv,
    );
    if (response === null) {
      throw new Error("expected health route response");
    }
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      status: "ok",
      auth_mode: "worker-api-token",
    });
  });

  it("rejects unauthenticated MCP requests when worker auth is enabled", async () => {
    const response = await maybeHandleNonMcpRequest(
      new Request("https://worker.example.test/mcp"),
      baseEnv,
    );
    if (response === null) {
      throw new Error("expected MCP auth response");
    }
    expect(response.status).toBe(401);
  });

  it("rejects unauthenticated download requests when worker auth is enabled", async () => {
    const response = await maybeHandleNonMcpRequest(
      new Request("https://worker.example.test/download/42"),
      baseEnv,
    );
    if (response === null) {
      throw new Error("expected download auth response");
    }
    expect(response.status).toBe(401);
  });

  it("allows health requests even when worker auth is enabled", async () => {
    const response = await maybeHandleNonMcpRequest(
      new Request("https://worker.example.test/"),
      baseEnv,
    );
    if (response === null) {
      throw new Error("expected root health response");
    }
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      status: "ok",
      has_origin_base_url: true,
    });
  });

  it("returns null for authenticated MCP requests so the MCP handler can continue", async () => {
    const response = await maybeHandleNonMcpRequest(
      new Request("https://worker.example.test/mcp", {
        headers: {
          Authorization: "Bearer worker-secret",
        },
      }),
      baseEnv,
    );
    expect(response).toBeNull();
  });
});
