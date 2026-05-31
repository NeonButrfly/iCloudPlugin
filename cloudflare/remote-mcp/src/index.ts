import { createMcpHandler } from "agents/mcp";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type Env = {
  ORIGIN_BASE_URL: string;
  ORIGIN_API_TOKEN: string;
  MCP_ROUTE?: string;
  DOWNLOAD_ROUTE_PREFIX?: string;
};

type JsonObject = Record<string, unknown>;

function buildOriginUrl(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  const normalizedPath = path.startsWith("/") ? path.slice(1) : path;
  return new URL(normalizedPath, normalizedBase).toString();
}

async function fetchOriginJson(
  env: Env,
  path: string,
  init?: RequestInit,
): Promise<JsonObject> {
  const response = await fetch(buildOriginUrl(env.ORIGIN_BASE_URL, path), {
    ...init,
    headers: {
      Authorization: `Bearer ${env.ORIGIN_API_TOKEN}`,
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Origin request failed (${response.status}): ${text}`);
  }
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Origin returned a non-object JSON payload");
  }
  return parsed as JsonObject;
}

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

function withWorkerDownloadUrl(
  payload: JsonObject,
  request: Request,
  env: Env,
): JsonObject {
  const downloadPath = payload.download_path;
  if (typeof downloadPath !== "string" || !downloadPath) {
    return payload;
  }
  const prefix = env.DOWNLOAD_ROUTE_PREFIX || "/download";
  const fileId = payload.file_id;
  if (typeof fileId !== "number") {
    return payload;
  }
  const workerDownloadUrl = new URL(`${prefix}/${fileId}`, request.url).toString();
  return {
    ...payload,
    worker_download_url: workerDownloadUrl,
  };
}

function createServer(env: Env, request: Request): McpServer {
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
    },
    async ({ query, limit, path_scope, hydrate_limit, max_chars, note_max_chars }) => {
      const params = new URLSearchParams({ query });
      if (typeof limit === "number") {
        params.set("limit", String(limit));
      }
      if (typeof path_scope === "string" && path_scope.trim()) {
        params.set("path_scope", path_scope);
      }

      const searchPayload = await fetchOriginJson(env, `/search?${params.toString()}`);
      const rawResults = Array.isArray(searchPayload.results) ? searchPayload.results : [];
      const hydratedBundles: JsonObject[] = [];
      const activeHydrateLimit = typeof hydrate_limit === "number" ? hydrate_limit : 3;

      for (const result of rawResults.slice(0, activeHydrateLimit)) {
        if (!result || typeof result !== "object" || Array.isArray(result)) {
          continue;
        }
        const fileId = result.file_id;
        if (typeof fileId !== "number" || fileId <= 0) {
          continue;
        }

        const filePayload = await fetchOriginJson(env, `/files/${fileId}`);
        if (
          typeof max_chars === "number" &&
          typeof filePayload.content_text === "string" &&
          filePayload.content_text.length > max_chars
        ) {
          filePayload.content_text = filePayload.content_text.slice(0, max_chars);
          filePayload.content_truncated = true;
        }

        const notePayload = await fetchOriginJson(env, `/files/${fileId}/note`);
        if (
          typeof note_max_chars === "number" &&
          typeof notePayload.note_content === "string" &&
          notePayload.note_content.length > note_max_chars
        ) {
          notePayload.note_content = notePayload.note_content.slice(0, note_max_chars);
          notePayload.note_truncated = true;
        }

        const sourcePayload = withWorkerDownloadUrl(
          await fetchOriginJson(env, `/files/${fileId}/source`),
          request,
          env,
        );

        hydratedBundles.push({
          match: result as JsonObject,
          file: filePayload,
          note: notePayload,
          source: sourcePayload,
        });
      }

      return jsonToolResult({
        ...searchPayload,
        hydrate_limit: activeHydrateLimit,
        hydrated_count: hydratedBundles.length,
        bundles: hydratedBundles,
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
    "refresh_icloud_index",
    {
      description: "Queue a metadata refresh on the backing cloud-vault index service.",
      inputSchema: {},
    },
    async () => {
      const payload = await fetchOriginJson(env, "/refresh", {
        method: "POST",
      });
      return jsonToolResult(payload);
    },
  );

  return server;
}

async function proxyDownload(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const prefix = env.DOWNLOAD_ROUTE_PREFIX || "/download";
  const fileIdText = url.pathname.startsWith(`${prefix}/`)
    ? url.pathname.slice(`${prefix}/`.length)
    : "";
  const fileId = Number.parseInt(fileIdText, 10);
  if (!Number.isFinite(fileId) || fileId <= 0) {
    return new Response("Not found", { status: 404 });
  }

  const originResponse = await fetch(
    buildOriginUrl(env.ORIGIN_BASE_URL, `/files/${fileId}/source/download`),
    {
      headers: {
        Authorization: `Bearer ${env.ORIGIN_API_TOKEN}`,
      },
    },
  );

  if (!originResponse.ok) {
    const text = await originResponse.text();
    return new Response(text || "Download unavailable", { status: originResponse.status });
  }

  const headers = new Headers(originResponse.headers);
  headers.set("Cache-Control", "private, no-store");
  return new Response(originResponse.body, {
    status: originResponse.status,
    headers,
  });
}

export default {
  fetch(request: Request, env: Env, ctx: ExecutionContext) {
    const url = new URL(request.url);
    const mcpRoute = env.MCP_ROUTE || "/mcp";
    const downloadPrefix = env.DOWNLOAD_ROUTE_PREFIX || "/download";

    if (url.pathname.startsWith(`${downloadPrefix}/`)) {
      return proxyDownload(request, env);
    }

    if (url.pathname === "/") {
      return new Response("iCloudPlugin Remote MCP", { status: 200 });
    }

    const server = createServer(env, request);
    return createMcpHandler(server, { route: mcpRoute })(request, env, ctx);
  },
} satisfies ExportedHandler<Env>;
