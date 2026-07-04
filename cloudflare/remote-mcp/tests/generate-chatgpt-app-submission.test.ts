import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import {
  buildSubmissionPayload,
  formatSubmissionPayload,
} from "../scripts/generate-chatgpt-app-submission.mjs";
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

describe("generate-chatgpt-app-submission", () => {
  let transport: StreamableHTTPClientTransport | null = null;
  let client: Client | null = null;

  beforeEach(() => {
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

  it("builds a submission payload for the current remote MCP surface", () => {
    const payload = buildSubmissionPayload();

    expect(payload.schema_version).toBe(1);
    expect(payload.app_info.display_name).toBe("iCloudPlugin Remote MCP");
    expect(Object.keys(payload.tools)).toEqual([
      "search_icloud_files",
      "search_icloud_notes_and_files",
      "get_icloud_system_status",
      "get_icloud_product_readiness",
      "get_icloud_change_set",
      "get_cloud_vault_task_status",
      "list_cloud_vault_tasks",
      "get_icloud_dedupe_job_status",
      "list_icloud_dedupe_groups",
      "get_icloud_dedupe_group",
      "get_icloud_file",
      "get_icloud_file_excerpt",
      "get_icloud_note",
      "get_icloud_source_reference",
      "get_icloud_file_bundle",
      "refresh_icloud_index",
      "pause_icloud_index",
      "resume_icloud_index",
      "create_document_vault_note",
      "continue_cloud_vault_task",
      "continue_cloud_vault_task_queue",
      "cancel_cloud_vault_task",
      "queue_create_document_vault_note_from_file_id_chatgpt_first",
      "queue_create_document_vault_notes_from_search",
      "queue_classifier_fallback_note_from_file_id",
      "classify_file_and_create_document_vault_note_fallback",
      "batch_classify_files_and_create_document_vault_notes_fallback",
      "search_files_and_create_document_vault_notes_fallback",
      "delete_icloud_file",
      "restore_icloud_change_set",
      "sync_icloud_manual_feedback_events",
      "analyze_icloud_duplicates",
      "queue_dedupe_analysis",
      "start_icloud_dedupe_job",
      "continue_icloud_dedupe_job",
      "apply_icloud_dedupe_group",
      "queue_apply_icloud_dedupe_group",
      "queue_restore_icloud_change_set",
    ]);
    expect(payload.test_cases.length).toBeGreaterThanOrEqual(5);
    expect(payload.negative_test_cases.length).toBeGreaterThanOrEqual(3);
  });

  it("formats the submission payload as stable pretty JSON", () => {
    const formatted = formatSubmissionPayload(buildSubmissionPayload());

    expect(formatted.endsWith("\n")).toBe(true);
    expect(formatted).toContain('"display_name": "iCloudPlugin Remote MCP"');
    expect(formatted).toContain('"refresh_icloud_index"');
    expect(formatted).toContain('"pause_icloud_index"');
    expect(formatted).toContain('"create_document_vault_note"');
    expect(formatted).toContain('"classify_file_and_create_document_vault_note_fallback"');
    expect(formatted).toContain('"get_icloud_change_set"');
    expect(formatted).toContain('"get_cloud_vault_task_status"');
    expect(formatted).toContain('"analyze_icloud_duplicates"');
    expect(formatted).toContain('"queue_dedupe_analysis"');
    expect(formatted).toContain('"start_icloud_dedupe_job"');
    expect(formatted).toContain('"apply_icloud_dedupe_group"');
  });

  it("keeps the submission tool metadata aligned with the actual Worker tool surface", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = toRequest(input, init);
      const url = new URL(request.url);

      if (url.host === "worker.example.test") {
        return worker.fetch(request, baseEnv, createExecutionContext());
      }

      throw new Error(`Unexpected host in test fetch: ${request.url}`);
    }) as typeof fetch;

    client = new Client({
      name: "submission-surface-test",
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

    const toolList = await client.listTools();
    const actualTools = new Map(toolList.tools.map((tool) => [tool.name, tool]));
    const submissionTools = buildSubmissionPayload().tools;

    expect(new Set(actualTools.keys())).toEqual(new Set(Object.keys(submissionTools)));

    for (const [toolName, expectedMetadata] of Object.entries(submissionTools)) {
      const actualTool = actualTools.get(toolName);
      expect(actualTool).toBeDefined();
      expect(actualTool?.annotations).toMatchObject(expectedMetadata.annotations);
      expect(actualTool?.outputSchema).toBeDefined();
    }
  });
});
