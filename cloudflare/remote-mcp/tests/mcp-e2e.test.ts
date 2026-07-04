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

        if (url.pathname === "/status/readiness") {
          return new Response(
            JSON.stringify({
              status_summary: {
                service_health: { status: "ok" },
                refresh_status: { status: "running", items_seen: 42, frontier_length: 7 },
              },
              product_readiness: {
                overall: { status: "incomplete" },
              },
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/files/ops/change-sets/abc123") {
          return new Response(
            JSON.stringify({
              change_set_id: "abc123",
              status: "deleted",
              items: [{ item_type: "source_file", namespace: "google1" }],
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/files/ops/dedupe/groups/dup123") {
          return new Response(
            JSON.stringify({
              dedupe_group_id: "dup123",
              status: "candidate",
              items: [{ path_at_analysis_time: "/google1/A.txt", decision_role: "canonical" }],
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

        if (url.pathname === "/files/ops/document-vault/note") {
          return new Response(
            JSON.stringify({
              note_path: "/vault/01 Classified/Appeal.md",
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/files/ops/delete") {
          return new Response(
            JSON.stringify({
              status: "deleted",
              change_set_id: "abc123",
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/files/ops/restore") {
          return new Response(
            JSON.stringify({
              status: "restored",
              change_set_id: "abc123",
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/files/ops/manual-feedback/sync") {
          return new Response(
            JSON.stringify({
              scanned: 2,
              created: 2,
              unchanged: 0,
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/files/ops/dedupe/analyze") {
          return new Response(
            JSON.stringify({
              created_groups: ["dup123"],
              groups: [
                {
                  dedupe_group_id: "dup123",
                  status: "candidate",
                  canonical_item_path: "/google1/A.txt",
                  duplicate_count: 1,
                  members: ["/google1/A.txt", "/google2/A.txt"],
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
    expect(toolNames).toContain("get_icloud_product_readiness");
    expect(toolNames).toContain("get_icloud_change_set");
    expect(toolNames).toContain("get_icloud_dedupe_group");
    expect(toolNames).toContain("search_icloud_notes_and_files");
    expect(toolNames).toContain("create_document_vault_note");
    expect(toolNames).toContain("classify_file_and_create_document_vault_note_fallback");
    expect(toolNames).toContain("batch_classify_files_and_create_document_vault_notes_fallback");
    expect(toolNames).toContain("search_files_and_create_document_vault_notes_fallback");
    expect(toolNames).toContain("delete_icloud_file");
    expect(toolNames).toContain("restore_icloud_change_set");
    expect(toolNames).toContain("sync_icloud_manual_feedback_events");
    expect(toolNames).toContain("analyze_icloud_duplicates");

    const readOnlyTool = toolList.tools.find((tool) => tool.name === "get_icloud_system_status");
    expect(readOnlyTool?.outputSchema).toBeDefined();
    expect(readOnlyTool?.annotations).toMatchObject({
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    });

    const writeTool = toolList.tools.find((tool) => tool.name === "refresh_icloud_index");
    expect(writeTool?.outputSchema).toBeDefined();
    expect(writeTool?.annotations).toMatchObject({
      readOnlyHint: false,
      openWorldHint: false,
      destructiveHint: false,
    });

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

  it("calls get_icloud_product_readiness through the Worker route", async () => {
    const connectedClient = await connectClient();

    const result = await connectedClient.callTool({
      name: "get_icloud_product_readiness",
      arguments: {},
    });

    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toMatchObject({
      product_readiness: {
        overall: { status: "incomplete" },
      },
    });

    const readinessRequest = originRequests.find(
      (request) => new URL(request.url).pathname === "/status/readiness",
    );
    expect(readinessRequest).toBeDefined();
    expect(readinessRequest?.headers.get("Authorization")).toBe("Bearer origin-secret");
  });

  it("falls back to status summary when the origin is missing /status/readiness", async () => {
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
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        if (url.pathname === "/status/readiness") {
          return new Response(JSON.stringify({ detail: "Not Found" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          });
        }

        throw new Error(`Unexpected origin request in test: ${request.url}`);
      }

      throw new Error(`Unexpected host in test fetch: ${request.url}`);
    }) as typeof fetch;

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

    const result = await client.callTool({
      name: "get_icloud_product_readiness",
      arguments: {},
    });

    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toMatchObject({
      fallback_mode: "status-summary",
      fallback_reason: "origin_missing_status_readiness",
      product_readiness: {
        overall: {
          status: "unknown",
        },
      },
      status_summary: {
        service_health: { status: "ok" },
        refresh_status: { status: "running", items_seen: 42, frontier_length: 7 },
      },
    });
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

  it("routes structured note creation and restore/delete mutations through the Worker", async () => {
    const connectedClient = await connectClient();

    const createResult = await connectedClient.callTool({
      name: "create_document_vault_note",
      arguments: {
        relative_folder: "01 Classified/appeal",
        visible_title: "Appeal",
        summary: "Appeal summary.",
        canonical_source_path: "/mnt/cloud-vault/mirrors/google1/Appeal.docx",
      },
    });
    expect(createResult.isError).not.toBe(true);
    expect(createResult.structuredContent).toMatchObject({
      note_path: "/vault/01 Classified/Appeal.md",
    });

    const deleteResult = await connectedClient.callTool({
      name: "delete_icloud_file",
      arguments: {
        namespace: "google1",
        relative_path: "Cases/Appeal.txt",
      },
    });
    expect(deleteResult.isError).not.toBe(true);
    expect(deleteResult.structuredContent).toMatchObject({
      status: "deleted",
      change_set_id: "abc123",
    });

    const restoreResult = await connectedClient.callTool({
      name: "restore_icloud_change_set",
      arguments: {
        change_set_id: "abc123",
      },
    });
    expect(restoreResult.isError).not.toBe(true);
    expect(restoreResult.structuredContent).toMatchObject({
      status: "restored",
      change_set_id: "abc123",
    });
  });

  it("reads indexed change-set history through the Worker", async () => {
    const connectedClient = await connectClient();

    const result = await connectedClient.callTool({
      name: "get_icloud_change_set",
      arguments: {
        change_set_id: "abc123",
      },
    });

    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toMatchObject({
      change_set_id: "abc123",
      status: "deleted",
      items: [{ item_type: "source_file", namespace: "google1" }],
    });
  });

  it("reads dedupe proposals and runs feedback/dedupe analysis through the Worker", async () => {
    const connectedClient = await connectClient();

    const dedupeRead = await connectedClient.callTool({
      name: "get_icloud_dedupe_group",
      arguments: {
        dedupe_group_id: "dup123",
      },
    });
    expect(dedupeRead.isError).not.toBe(true);
    expect(dedupeRead.structuredContent).toMatchObject({
      dedupe_group_id: "dup123",
      status: "candidate",
    });

    const feedbackSync = await connectedClient.callTool({
      name: "sync_icloud_manual_feedback_events",
      arguments: {
        limit: 10,
      },
    });
    expect(feedbackSync.isError).not.toBe(true);
    expect(feedbackSync.structuredContent).toMatchObject({
      scanned: 2,
      created: 2,
    });

    const dedupeAnalyze = await connectedClient.callTool({
      name: "analyze_icloud_duplicates",
      arguments: {
        namespaces: ["google1", "google2", "icloud"],
        limit: 10,
      },
    });
    expect(dedupeAnalyze.isError).not.toBe(true);
    expect(dedupeAnalyze.structuredContent).toMatchObject({
      created_groups: ["dup123"],
    });
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
