import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  fetchOriginJson,
  maybeHandleNonMcpRequest,
  type Env,
  type JsonObject,
  withWorkerDownloadUrl,
} from "./runtime";
import { createMcpHandler } from "./mcpHandler";

function jsonToolResult(payload: JsonObject) {
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(payload, null, 2),
      },
    ],
    structuredContent: payload,
  };
}

function isMissingReadinessRoute(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("Origin request failed (404)");
}

const genericJsonObjectSchema = z.object({}).passthrough();
const readOnlyPrivateAnnotations = {
  readOnlyHint: true,
  openWorldHint: false,
  destructiveHint: false,
} as const;
const internalWriteAnnotations = {
  readOnlyHint: false,
  openWorldHint: false,
  destructiveHint: false,
} as const;

export function createServer(env: Env, request: Request): McpServer {
  const server = new McpServer({
    name: "iCloudPlugin Remote MCP",
    version: "0.1.0",
  });

  server.registerTool(
    "search_icloud_files",
    {
      description: "Search indexed cloud-vault files by name, path, classifier metadata, and extracted text.",
      inputSchema: {
        query: z.string().min(1),
        limit: z.number().int().min(1).max(50).optional(),
        path_scope: z.string().optional(),
      },
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async ({ query, limit, path_scope }) => {
      const params = new URLSearchParams({ query });
      if (typeof limit === "number") {
        params.set("limit", String(limit));
      }
      if (typeof path_scope === "string" && path_scope.trim()) {
        params.set("path_scope", path_scope);
      }
      const payload = await fetchOriginJson(env, `/search?${params.toString()}`);
      return jsonToolResult(payload);
    },
  );

  server.registerTool(
    "search_icloud_notes_and_files",
    {
      description:
        "Search indexed cloud-vault files, then expand the top matches into note-plus-source bundles for faster analysis.",
      inputSchema: {
        query: z.string().min(1),
        limit: z.number().int().min(1).max(50).optional(),
        path_scope: z.string().optional(),
        hydrate_limit: z.number().int().min(0).max(10).optional(),
        max_chars: z.number().int().min(1).max(10000).optional(),
        note_max_chars: z.number().int().min(1).max(50000).optional(),
      },
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async ({ query, limit, path_scope, hydrate_limit, max_chars, note_max_chars }) => {
      const params = new URLSearchParams({ query });
      if (typeof limit === "number") {
        params.set("limit", String(limit));
      }
      if (typeof path_scope === "string" && path_scope.trim()) {
        params.set("path_scope", path_scope);
      }
      const activeHydrateLimit = typeof hydrate_limit === "number" ? hydrate_limit : 3;
      params.set("hydrate_limit", String(activeHydrateLimit));
      if (typeof max_chars === "number") {
        params.set("max_chars", String(max_chars));
      }
      if (typeof note_max_chars === "number") {
        params.set("note_max_chars", String(note_max_chars));
      }

      const payload = await fetchOriginJson(env, `/search/bundles?${params.toString()}`);
      const rawBundles = Array.isArray(payload.bundles) ? payload.bundles : [];
      const bundles = rawBundles.map((bundle) => {
        if (!bundle || typeof bundle !== "object" || Array.isArray(bundle)) {
          return bundle;
        }
        const sourcePayload = bundle.source;
        if (!sourcePayload || typeof sourcePayload !== "object" || Array.isArray(sourcePayload)) {
          return bundle;
        }
        return {
          ...bundle,
          source: withWorkerDownloadUrl(sourcePayload as JsonObject, request, env),
        };
      });
      return jsonToolResult({
        ...payload,
        bundles,
        hydrated_count: Array.isArray(bundles) ? bundles.length : payload.hydrated_count,
      });
    },
  );

  server.registerTool(
    "get_icloud_file",
    {
      description: "Get indexed metadata and extracted content for a specific file.",
      inputSchema: {
        file_id: z.number().int().positive(),
      },
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async ({ file_id }) => {
      const payload = await fetchOriginJson(env, `/files/${file_id}`);
      return jsonToolResult(payload);
    },
  );

  server.registerTool(
    "get_icloud_file_excerpt",
    {
      description: "Get indexed metadata plus a lighter extracted-content payload for a file.",
      inputSchema: {
        file_id: z.number().int().positive(),
        max_chars: z.number().int().min(1).max(10000).optional(),
      },
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async ({ file_id, max_chars }) => {
      const payload = await fetchOriginJson(env, `/files/${file_id}`);
      if (
        typeof max_chars === "number" &&
        typeof payload.content_text === "string" &&
        payload.content_text.length > max_chars
      ) {
        payload.content_text = payload.content_text.slice(0, max_chars);
        payload.content_truncated = true;
      }
      return jsonToolResult(payload);
    },
  );

  server.registerTool(
    "get_icloud_note",
    {
      description: "Get the generated Obsidian note content and note metadata for a file.",
      inputSchema: {
        file_id: z.number().int().positive(),
        max_chars: z.number().int().min(1).max(50000).optional(),
      },
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async ({ file_id, max_chars }) => {
      const payload = await fetchOriginJson(env, `/files/${file_id}/note`);
      if (
        typeof max_chars === "number" &&
        typeof payload.note_content === "string" &&
        payload.note_content.length > max_chars
      ) {
        payload.note_content = payload.note_content.slice(0, max_chars);
        payload.note_truncated = true;
      }
      return jsonToolResult(payload);
    },
  );

  server.registerTool(
    "get_icloud_source_reference",
    {
      description: "Get canonical source-path, source-link, and download-handoff metadata for a file.",
      inputSchema: {
        file_id: z.number().int().positive(),
      },
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async ({ file_id }) => {
      const payload = await fetchOriginJson(env, `/files/${file_id}/source`);
      return jsonToolResult(withWorkerDownloadUrl(payload, request, env));
    },
  );

  server.registerTool(
    "get_icloud_file_bundle",
    {
      description: "Get file metadata, source excerpt, note content, and source handoff details together.",
      inputSchema: {
        file_id: z.number().int().positive(),
        max_chars: z.number().int().min(1).max(10000).optional(),
        note_max_chars: z.number().int().min(1).max(50000).optional(),
      },
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async ({ file_id, max_chars, note_max_chars }) => {
      const filePayload = await fetchOriginJson(env, `/files/${file_id}`);
      if (
        typeof max_chars === "number" &&
        typeof filePayload.content_text === "string" &&
        filePayload.content_text.length > max_chars
      ) {
        filePayload.content_text = filePayload.content_text.slice(0, max_chars);
        filePayload.content_truncated = true;
      }
      const notePayload = await fetchOriginJson(env, `/files/${file_id}/note`);
      if (
        typeof note_max_chars === "number" &&
        typeof notePayload.note_content === "string" &&
        notePayload.note_content.length > note_max_chars
      ) {
        notePayload.note_content = notePayload.note_content.slice(0, note_max_chars);
        notePayload.note_truncated = true;
      }
      const sourcePayload = withWorkerDownloadUrl(
        await fetchOriginJson(env, `/files/${file_id}/source`),
        request,
        env,
      );
      return jsonToolResult({
        file: filePayload,
        note: notePayload,
        source: sourcePayload,
      });
    },
  );

  server.registerTool(
    "get_icloud_system_status",
    {
      description:
        "Get live cloud-vault service health, refresh progress, classifier readiness, and queue counts.",
      inputSchema: {},
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async () => {
      const payload = await fetchOriginJson(env, "/status/summary");
      return jsonToolResult(payload);
    },
  );

  server.registerTool(
    "get_icloud_product_readiness",
    {
      description:
        "Get a consolidated product-readiness report showing which end-to-end cloud-vault criteria are met, blocked, or still unknown.",
      inputSchema: {},
      outputSchema: genericJsonObjectSchema,
      annotations: readOnlyPrivateAnnotations,
    },
    async () => {
      try {
        const payload = await fetchOriginJson(env, "/status/readiness");
        return jsonToolResult(payload);
      } catch (error) {
        if (!isMissingReadinessRoute(error)) {
          throw error;
        }

        const summaryPayload = await fetchOriginJson(env, "/status/summary");
        return jsonToolResult({
          fallback_mode: "status-summary",
          fallback_reason: "origin_missing_status_readiness",
          status_summary: summaryPayload,
          product_readiness: {
            overall: {
              status: "unknown",
              detail:
                "The origin service does not currently expose /status/readiness, so this hosted MCP response is falling back to /status/summary.",
            },
          },
        });
      }
    },
  );

  server.registerTool(
    "refresh_icloud_index",
    {
      description: "Queue a metadata refresh on the backing cloud-vault index service.",
      inputSchema: {},
      outputSchema: genericJsonObjectSchema,
      annotations: internalWriteAnnotations,
    },
    async () => {
      const payload = await fetchOriginJson(env, "/refresh", {
        method: "POST",
      });
      return jsonToolResult(payload);
    },
  );

  server.registerTool(
    "pause_icloud_index",
    {
      description: "Pause background metadata refresh work on the backing cloud-vault index service.",
      inputSchema: {},
      outputSchema: genericJsonObjectSchema,
      annotations: internalWriteAnnotations,
    },
    async () => {
      const payload = await fetchOriginJson(env, "/refresh/pause", {
        method: "POST",
      });
      return jsonToolResult(payload);
    },
  );

  server.registerTool(
    "resume_icloud_index",
    {
      description: "Resume paused background metadata refresh work from the saved cloud-vault frontier.",
      inputSchema: {},
      outputSchema: genericJsonObjectSchema,
      annotations: internalWriteAnnotations,
    },
    async () => {
      const payload = await fetchOriginJson(env, "/refresh/resume", {
        method: "POST",
      });
      return jsonToolResult(payload);
    },
  );

  return server;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext) {
    const mcpRoute = env.MCP_ROUTE || "/mcp";
    const earlyResponse = await maybeHandleNonMcpRequest(request, env);
    if (earlyResponse) {
      return earlyResponse;
    }

    const server = createServer(env, request);
    return createMcpHandler(server, { route: mcpRoute })(request);
  },
} satisfies ExportedHandler<Env>;
