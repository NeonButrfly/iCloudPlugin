import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import worker from "../src/index";

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

const workerBaseUrl = "https://worker.example.test";
const originalFetch = globalThis.fetch;

function toRequest(input: RequestInfo | URL, init?: RequestInit): Request {
  if (input instanceof Request && !init) {
    return input;
  }
  if (input instanceof Request) {
    return new Request(input, init);
  }
  return new Request(String(input), init);
}

function createExecutionContext(): ExecutionContext {
  return {
    waitUntil() {},
    passThroughOnException() {},
    props: {},
  } as ExecutionContext;
}

describe("remote MCP worker end-to-end", () => {
  let originRequests: Request[] = [];
  let transport: StreamableHTTPClientTransport | null = null;
  let client: Client | null = null;

  beforeEach(() => {
    originRequests = [];
    vi.restoreAllMocks();
  });

  afterEach(async () => {
    if (transport) {
      await transport.close().catch(() => undefined);
    }
    transport = null;
    client = null;
    globalThis.fetch = originalFetch;
  });

  function installFetchMock() {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = toRequest(input, init);
      const url = new URL(request.url);

      if (url.host === "worker.example.test") {
        return worker.fetch(request, baseEnv, createExecutionContext());
      }

      if (url.host === "origin.example.test") {
        originRequests.push(request);

        if (url.pathname === "/status/summary") {
          return new Response(
            JSON.stringify({
              service_health: { status: "ok" },
              refresh_status: { status: "running", items_seen: 42, frontier_length: 7 },
              classifier_health: { ok: true },
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/search/bundles") {
          return new Response(
            JSON.stringify({
              total: 1,
              hydrate_limit: 1,
              hydrated_count: 1,
              bundles: [
                {
                  match: { file_id: 42, path: "/icloud/example.txt" },
                  file: { file_id: 42, title: "example" },
                  note: {
                    note_available: true,
                    note_path: "01 Classified/technical/example - technical.md",
                  },
                  source: {
                    file_id: 42,
                    download_path: "/files/42/source/download",
                    source_link: "\\\\192.168.50.86\\cloud-vault\\mirrors\\icloud\\example.txt",
                  },
                },
              ],
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        throw new Error(`Unexpected origin request in test: ${request.url}`);
      }

      throw new Error(`Unexpected host in test fetch: ${request.url}`);
    }) as typeof fetch;
  }

  async function connectClient() {
    installFetchMock();
    client = new Client({
      name: "remote-mcp-e2e-test",
      version: "0.1.0",
    });
    transport = new StreamableHTTPClientTransport(new URL(`${workerBaseUrl}/mcp`), {
      requestInit: {
        headers: {
          Authorization: "Bearer worker-secret",
        },
      },
      fetch: globalThis.fetch,
    });
    await client.connect(transport);
    return client;
  }

  it("lists tools and calls get_icloud_system_status through the Worker route", async () => {
    const connectedClient = await connectClient();

    const toolList = await connectedClient.listTools();
    const toolNames = toolList.tools.map((tool) => tool.name);
    expect(toolNames).toContain("get_icloud_system_status");
    expect(toolNames).toContain("search_icloud_notes_and_files");

    const result = await connectedClient.callTool({
      name: "get_icloud_system_status",
      arguments: {},
    });

    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toMatchObject({
      service_health: { status: "ok" },
      refresh_status: { status: "running", items_seen: 42, frontier_length: 7 },
      classifier_health: { ok: true },
    });

    const statusRequest = originRequests.find(
      (request) => new URL(request.url).pathname === "/status/summary",
    );
    expect(statusRequest).toBeDefined();
    expect(statusRequest?.headers.get("Authorization")).toBe("Bearer origin-secret");
  });

  it("rewrites worker download URLs in bundled search results", async () => {
    const connectedClient = await connectClient();

    const result = await connectedClient.callTool({
      name: "search_icloud_notes_and_files",
      arguments: {
        query: "example",
        hydrate_limit: 1,
      },
    });

    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toMatchObject({
      hydrated_count: 1,
      bundles: [
        {
          source: {
            file_id: 42,
            worker_download_url: `${workerBaseUrl}/download/42`,
          },
        },
      ],
    });

    const bundleRequest = originRequests.find(
      (request) => new URL(request.url).pathname === "/search/bundles",
    );
    expect(bundleRequest).toBeDefined();
    expect(bundleRequest?.headers.get("Authorization")).toBe("Bearer origin-secret");
  });

  it("returns 405 on direct GET /mcp so streamable-http clients can fall through cleanly", async () => {
    installFetchMock();

    const response = await worker.fetch(
      new Request(`${workerBaseUrl}/mcp`, {
        method: "GET",
        headers: {
          Authorization: "Bearer worker-secret",
        },
      }),
      baseEnv,
      createExecutionContext(),
    );

    expect(response.status).toBe(405);
    expect(response.headers.get("Allow")).toBe("POST, DELETE");
    await expect(response.text()).resolves.toBe("Method Not Allowed");
  });
});
