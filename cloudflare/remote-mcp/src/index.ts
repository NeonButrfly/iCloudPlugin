type Env = {
  ORIGIN_BASE_URL: string;
  ORIGIN_API_TOKEN: string;
  WORKER_API_TOKEN?: string;
  MCP_ROUTE?: string;
  DOWNLOAD_ROUTE_PREFIX?: string;
  HEALTH_ROUTE?: string;
};

type JsonValue = string | number | boolean | null | JsonObject | JsonValue[];
type JsonObject = { [key: string]: JsonValue | undefined };

type ToolAnnotations = {
  readOnlyHint: boolean;
  openWorldHint: boolean;
  destructiveHint: boolean;
};

type ToolDefinition = {
  name: string;
  description: string;
  inputSchema: JsonObject;
  outputSchema: JsonObject;
  annotations: ToolAnnotations;
  handler: (context: ToolContext, args: JsonObject) => Promise<JsonObject>;
};

type ToolContext = {
  env: Env;
  request: Request;
};

const SERVER_NAME = "iCloudPlugin Remote MCP";
const SERVER_VERSION = "0.1.0";
const MCP_PROTOCOL_VERSION = "2025-03-26";
const DEFAULT_MCP_ROUTE = "/mcp";
const DEFAULT_DOWNLOAD_ROUTE_PREFIX = "/download";
const DEFAULT_HEALTH_ROUTE = "/healthz";
const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "private, no-store",
};

const READ_ONLY_ANNOTATIONS: ToolAnnotations = {
  readOnlyHint: true,
  openWorldHint: false,
  destructiveHint: false,
};

const WRITE_ANNOTATIONS: ToolAnnotations = {
  readOnlyHint: false,
  openWorldHint: false,
  destructiveHint: false,
};

const GENERIC_OBJECT_SCHEMA: JsonObject = {
  type: "object",
  additionalProperties: true,
};

function buildOriginUrl(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  const normalizedPath = path.startsWith("/") ? path.slice(1) : path;
  return new URL(normalizedPath, normalizedBase).toString();
}

function buildWorkerUrl(request: Request, route: string): string {
  return new URL(route, request.url).toString();
}

function getMcpRoute(env: Env): string {
  return env.MCP_ROUTE || DEFAULT_MCP_ROUTE;
}

function getDownloadRoute(env: Env): string {
  return env.DOWNLOAD_ROUTE_PREFIX || DEFAULT_DOWNLOAD_ROUTE_PREFIX;
}

function getHealthRoute(env: Env): string {
  return env.HEALTH_ROUTE || DEFAULT_HEALTH_ROUTE;
}

function jsonResponse(payload: JsonValue, status = 200): Response {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: JSON_HEADERS,
  });
}

function unauthorizedResponse(): Response {
  return jsonResponse(
    {
      error: "unauthorized",
      detail: "A valid bearer token is required for this remote MCP server.",
    },
    401,
  );
}

function mcpError(id: JsonValue, code: number, message: string, status = 200): Response {
  return jsonResponse(
    {
      jsonrpc: "2.0",
      id,
      error: { code, message },
    },
    status,
  );
}

function trimString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asObject(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as JsonObject;
}

function readString(value: unknown, field: string): string {
  const trimmed = trimString(value);
  if (!trimmed) {
    throw new Error(`Invalid or missing ${field}.`);
  }
  return trimmed;
}

function readOptionalString(value: unknown): string | undefined {
  const trimmed = trimString(value);
  return trimmed || undefined;
}

function readPositiveInt(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
    throw new Error(`Invalid ${field}; expected a positive integer.`);
  }
  return value;
}

function readOptionalBoundedInt(
  value: unknown,
  field: string,
  min: number,
  max: number,
): number | undefined {
  if (typeof value === "undefined") {
    return undefined;
  }
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    throw new Error(`Invalid ${field}; expected an integer between ${min} and ${max}.`);
  }
  return value;
}

function readBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`Invalid ${field}; expected a boolean.`);
  }
  return value;
}

function readStringArray(
  value: unknown,
  field: string,
  allowed: readonly string[],
): string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`Invalid ${field}; expected a non-empty array.`);
  }
  const output = value.map((entry) => readString(entry, field));
  for (const entry of output) {
    if (!allowed.includes(entry)) {
      throw new Error(`Invalid ${field}; unsupported value "${entry}".`);
    }
  }
  return output;
}

async function sha256Bytes(value: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
}

function timingSafeEqualBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) {
    return false;
  }
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) {
    diff |= left[index] ^ right[index];
  }
  return diff === 0;
}

async function hasValidWorkerApiToken(request: Request, env: Env): Promise<boolean> {
  const configuredToken = trimString(env.WORKER_API_TOKEN);
  if (!configuredToken) {
    return true;
  }
  const authorization = request.headers.get("Authorization") || "";
  if (!authorization.startsWith("Bearer ")) {
    return false;
  }
  const candidate = authorization.slice("Bearer ".length).trim();
  if (!candidate) {
    return false;
  }
  const [left, right] = await Promise.all([sha256Bytes(candidate), sha256Bytes(configuredToken)]);
  return timingSafeEqualBytes(left, right);
}

async function fetchOriginJson(
  env: Env,
  path: string,
  init?: RequestInit,
): Promise<JsonObject> {
  const response = await fetch(buildOriginUrl(env.ORIGIN_BASE_URL, path), {
    ...init,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${env.ORIGIN_API_TOKEN}`,
      ...(init?.headers || {}),
    },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Origin request failed (${response.status}): ${text}`);
  }
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Origin returned a non-object JSON payload.");
  }
  return parsed as JsonObject;
}

function withWorkerDownloadUrl(payload: JsonObject, request: Request, env: Env): JsonObject {
  const fileId = payload.file_id;
  const downloadPath = payload.download_path;
  if (typeof fileId !== "number" || typeof downloadPath !== "string" || !downloadPath) {
    return payload;
  }
  const route = `${getDownloadRoute(env)}/${fileId}`;
  return {
    ...payload,
    worker_download_url: buildWorkerUrl(request, route),
  };
}

function buildHealthPayload(env: Env, request: Request): JsonObject {
  return {
    status: "ok",
    name: SERVER_NAME,
    version: SERVER_VERSION,
    auth_mode: trimString(env.WORKER_API_TOKEN) ? "worker-api-token" : "origin-only",
    mcp_route: buildWorkerUrl(request, getMcpRoute(env)),
    download_route_prefix: buildWorkerUrl(request, getDownloadRoute(env)),
    health_route: buildWorkerUrl(request, getHealthRoute(env)),
    has_origin_base_url: Boolean(trimString(env.ORIGIN_BASE_URL)),
    has_origin_api_token: Boolean(trimString(env.ORIGIN_API_TOKEN)),
  };
}

async function proxyDownload(request: Request, env: Env): Promise<Response> {
  const pathname = new URL(request.url).pathname;
  const prefix = `${getDownloadRoute(env)}/`;
  const rawFileId = pathname.startsWith(prefix) ? pathname.slice(prefix.length) : "";
  const fileId = Number.parseInt(rawFileId, 10);
  if (!Number.isFinite(fileId) || fileId <= 0) {
    return new Response("Not found", { status: 404 });
  }
  const originResponse = await fetch(buildOriginUrl(env.ORIGIN_BASE_URL, `/files/${fileId}/source/download`), {
    headers: {
      Authorization: `Bearer ${env.ORIGIN_API_TOKEN}`,
    },
  });
  if (!originResponse.ok) {
    const detail = await originResponse.text();
    return new Response(detail || "Download unavailable", { status: originResponse.status });
  }
  const headers = new Headers(originResponse.headers);
  headers.set("Cache-Control", "private, no-store");
  return new Response(originResponse.body, {
    status: originResponse.status,
    headers,
  });
}

function jsonToolResult(payload: JsonObject): JsonObject {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(payload, null, 2),
      },
    ],
    structuredContent: payload,
  };
}

function isMissingReadinessRoute(error: unknown): boolean {
  return (error instanceof Error ? error.message : String(error)).includes(
    "Origin request failed (404)",
  );
}

const TOOL_DEFINITIONS: ToolDefinition[] = [
  {
    name: "search_icloud_files",
    description:
      "Search indexed cloud-vault files by name, path, classifier metadata, and extracted text.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", minLength: 1 },
        limit: { type: "integer", minimum: 1, maximum: 50 },
        path_scope: { type: "string" },
      },
      required: ["query"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) => {
      const params = new URLSearchParams({ query: readString(args.query, "query") });
      const limit = readOptionalBoundedInt(args.limit, "limit", 1, 50);
      const pathScope = readOptionalString(args.path_scope);
      if (typeof limit === "number") {
        params.set("limit", String(limit));
      }
      if (pathScope) {
        params.set("path_scope", pathScope);
      }
      return fetchOriginJson(env, `/search?${params.toString()}`);
    },
  },
  {
    name: "search_icloud_notes_and_files",
    description:
      "Search indexed cloud-vault files, then expand the top matches into note-plus-source bundles for faster analysis.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", minLength: 1 },
        limit: { type: "integer", minimum: 1, maximum: 50 },
        path_scope: { type: "string" },
        hydrate_limit: { type: "integer", minimum: 0, maximum: 10 },
        max_chars: { type: "integer", minimum: 1, maximum: 10000 },
        note_max_chars: { type: "integer", minimum: 1, maximum: 50000 },
      },
      required: ["query"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env, request }, args) => {
      const params = new URLSearchParams({ query: readString(args.query, "query") });
      const limit = readOptionalBoundedInt(args.limit, "limit", 1, 50);
      const pathScope = readOptionalString(args.path_scope);
      const hydrateLimit = readOptionalBoundedInt(args.hydrate_limit, "hydrate_limit", 0, 10);
      const maxChars = readOptionalBoundedInt(args.max_chars, "max_chars", 1, 10000);
      const noteMaxChars = readOptionalBoundedInt(
        args.note_max_chars,
        "note_max_chars",
        1,
        50000,
      );
      if (typeof limit === "number") {
        params.set("limit", String(limit));
      }
      if (pathScope) {
        params.set("path_scope", pathScope);
      }
      params.set("hydrate_limit", String(typeof hydrateLimit === "number" ? hydrateLimit : 3));
      if (typeof maxChars === "number") {
        params.set("max_chars", String(maxChars));
      }
      if (typeof noteMaxChars === "number") {
        params.set("note_max_chars", String(noteMaxChars));
      }
      const payload = await fetchOriginJson(env, `/search/bundles?${params.toString()}`);
      const bundles = Array.isArray(payload.bundles)
        ? payload.bundles.map((bundle) => {
            if (!bundle || typeof bundle !== "object" || Array.isArray(bundle)) {
              return bundle as JsonValue;
            }
            const source = (bundle as JsonObject).source;
            if (!source || typeof source !== "object" || Array.isArray(source)) {
              return bundle as JsonValue;
            }
            return {
              ...(bundle as JsonObject),
              source: withWorkerDownloadUrl(source as JsonObject, request, env),
            } satisfies JsonObject;
          })
        : [];
      return {
        ...payload,
        bundles,
        hydrated_count: bundles.length,
      };
    },
  },
  {
    name: "get_icloud_file",
    description: "Get indexed metadata and extracted content for a specific file.",
    inputSchema: {
      type: "object",
      properties: {
        file_id: { type: "integer", minimum: 1 },
      },
      required: ["file_id"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) => fetchOriginJson(env, `/files/${readPositiveInt(args.file_id, "file_id")}`),
  },
  {
    name: "get_icloud_file_excerpt",
    description: "Get indexed metadata plus a lighter extracted-content payload for a file.",
    inputSchema: {
      type: "object",
      properties: {
        file_id: { type: "integer", minimum: 1 },
        max_chars: { type: "integer", minimum: 1, maximum: 10000 },
      },
      required: ["file_id"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) => {
      const fileId = readPositiveInt(args.file_id, "file_id");
      const maxChars = readOptionalBoundedInt(args.max_chars, "max_chars", 1, 10000);
      const payload = await fetchOriginJson(env, `/files/${fileId}`);
      if (
        typeof maxChars === "number" &&
        typeof payload.content_text === "string" &&
        payload.content_text.length > maxChars
      ) {
        payload.content_text = payload.content_text.slice(0, maxChars);
        payload.content_truncated = true;
      }
      return payload;
    },
  },
  {
    name: "get_icloud_note",
    description: "Get the generated Obsidian note content and note metadata for a file.",
    inputSchema: {
      type: "object",
      properties: {
        file_id: { type: "integer", minimum: 1 },
        max_chars: { type: "integer", minimum: 1, maximum: 50000 },
      },
      required: ["file_id"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) => {
      const fileId = readPositiveInt(args.file_id, "file_id");
      const maxChars = readOptionalBoundedInt(args.max_chars, "max_chars", 1, 50000);
      const payload = await fetchOriginJson(env, `/files/${fileId}/note`);
      if (
        typeof maxChars === "number" &&
        typeof payload.note_content === "string" &&
        payload.note_content.length > maxChars
      ) {
        payload.note_content = payload.note_content.slice(0, maxChars);
        payload.note_truncated = true;
      }
      return payload;
    },
  },
  {
    name: "get_icloud_source_reference",
    description: "Get canonical source-path, source-link, and download-handoff metadata for a file.",
    inputSchema: {
      type: "object",
      properties: {
        file_id: { type: "integer", minimum: 1 },
      },
      required: ["file_id"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env, request }, args) =>
      withWorkerDownloadUrl(
        await fetchOriginJson(env, `/files/${readPositiveInt(args.file_id, "file_id")}/source`),
        request,
        env,
      ),
  },
  {
    name: "get_icloud_file_bundle",
    description: "Get file metadata, source excerpt, note content, and source handoff details together.",
    inputSchema: {
      type: "object",
      properties: {
        file_id: { type: "integer", minimum: 1 },
        max_chars: { type: "integer", minimum: 1, maximum: 10000 },
        note_max_chars: { type: "integer", minimum: 1, maximum: 50000 },
      },
      required: ["file_id"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env, request }, args) => {
      const fileId = readPositiveInt(args.file_id, "file_id");
      const maxChars = readOptionalBoundedInt(args.max_chars, "max_chars", 1, 10000);
      const noteMaxChars = readOptionalBoundedInt(args.note_max_chars, "note_max_chars", 1, 50000);
      const filePayload = await fetchOriginJson(env, `/files/${fileId}`);
      if (
        typeof maxChars === "number" &&
        typeof filePayload.content_text === "string" &&
        filePayload.content_text.length > maxChars
      ) {
        filePayload.content_text = filePayload.content_text.slice(0, maxChars);
        filePayload.content_truncated = true;
      }
      const notePayload = await fetchOriginJson(env, `/files/${fileId}/note`);
      if (
        typeof noteMaxChars === "number" &&
        typeof notePayload.note_content === "string" &&
        notePayload.note_content.length > noteMaxChars
      ) {
        notePayload.note_content = notePayload.note_content.slice(0, noteMaxChars);
        notePayload.note_truncated = true;
      }
      return {
        file: filePayload,
        note: notePayload,
        source: withWorkerDownloadUrl(
          await fetchOriginJson(env, `/files/${fileId}/source`),
          request,
          env,
        ),
      };
    },
  },
  {
    name: "get_icloud_system_status",
    description:
      "Get live cloud-vault service health, refresh progress, classifier readiness, and queue counts.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }) => fetchOriginJson(env, "/status/summary"),
  },
  {
    name: "get_icloud_product_readiness",
    description:
      "Get a consolidated product-readiness report showing which end-to-end cloud-vault criteria are met, blocked, or still unknown.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }) => {
      try {
        return await fetchOriginJson(env, "/status/readiness");
      } catch (error) {
        if (!isMissingReadinessRoute(error)) {
          throw error;
        }
        return {
          fallback_mode: "status-summary",
          fallback_reason: "origin_missing_status_readiness",
          status_summary: await fetchOriginJson(env, "/status/summary"),
          product_readiness: {
            overall: {
              status: "unknown",
              detail:
                "The origin service does not currently expose /status/readiness, so this hosted MCP response is falling back to /status/summary.",
            },
          },
        };
      }
    },
  },
  {
    name: "get_icloud_change_set",
    description: "Get indexed metadata and item history for a reversible change set.",
    inputSchema: {
      type: "object",
      properties: {
        change_set_id: { type: "string", minLength: 1 },
      },
      required: ["change_set_id"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) =>
      fetchOriginJson(env, `/files/ops/change-sets/${encodeURIComponent(readString(args.change_set_id, "change_set_id"))}`),
  },
  {
    name: "get_icloud_dedupe_group",
    description: "Get indexed metadata and member items for a duplicate-group proposal.",
    inputSchema: {
      type: "object",
      properties: {
        dedupe_group_id: { type: "string", minLength: 1 },
      },
      required: ["dedupe_group_id"],
      additionalProperties: false,
    },
    annotations: READ_ONLY_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) =>
      fetchOriginJson(env, `/files/ops/dedupe/groups/${encodeURIComponent(readString(args.dedupe_group_id, "dedupe_group_id"))}`),
  },
  {
    name: "refresh_icloud_index",
    description: "Queue a metadata refresh on the backing cloud-vault index service.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }) => fetchOriginJson(env, "/refresh", { method: "POST" }),
  },
  {
    name: "pause_icloud_index",
    description: "Pause background metadata refresh work on the backing cloud-vault index service.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }) => fetchOriginJson(env, "/refresh/pause", { method: "POST" }),
  },
  {
    name: "resume_icloud_index",
    description: "Resume paused background metadata refresh work from the saved cloud-vault frontier.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }) => fetchOriginJson(env, "/refresh/resume", { method: "POST" }),
  },
  {
    name: "create_document_vault_note",
    description:
      "Create a structured Obsidian note in document_vault using the categorizer-compatible note contract.",
    inputSchema: {
      type: "object",
      properties: {
        relative_folder: { type: "string", minLength: 1 },
        visible_title: { type: "string", minLength: 1 },
        summary: { type: "string", minLength: 1 },
        file_id: { type: "integer", minimum: 1 },
        canonical_source_path: { type: "string", minLength: 1 },
        attach_originals: { type: "boolean" },
      },
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) => {
      const body: Record<string, unknown> = {
        relative_folder: readString(args.relative_folder, "relative_folder"),
        visible_title: readString(args.visible_title, "visible_title"),
        summary: readString(args.summary, "summary"),
        attach_originals:
          typeof args.attach_originals === "undefined"
            ? true
            : readBoolean(args.attach_originals, "attach_originals"),
      };
      if (typeof args.file_id !== "undefined") {
        body.file_id = readPositiveInt(args.file_id, "file_id");
      }
      if (typeof args.canonical_source_path !== "undefined") {
        body.canonical_source_path = readString(
          args.canonical_source_path,
          "canonical_source_path",
        );
      }
      if (typeof body.file_id === "undefined" && typeof body.canonical_source_path === "undefined") {
        throw new Error("Either file_id or canonical_source_path is required.");
      }
      return fetchOriginJson(env, "/files/ops/document-vault/note", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
    },
  },
  {
    name: "delete_icloud_file",
    description:
      "Move a live file into the namespace-specific _CHANGES_BACKUP area and return a reversible change set.",
    inputSchema: {
      type: "object",
      properties: {
        namespace: {
          type: "string",
          enum: ["google1", "google2", "icloud", "document_vault"],
        },
        relative_path: { type: "string", minLength: 1 },
      },
      required: ["namespace", "relative_path"],
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) => {
      const namespace = readString(args.namespace, "namespace");
      if (!["google1", "google2", "icloud", "document_vault"].includes(namespace)) {
        throw new Error("Invalid namespace.");
      }
      return fetchOriginJson(env, "/files/ops/delete", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          namespace,
          relative_path: readString(args.relative_path, "relative_path"),
        }),
      });
    },
  },
  {
    name: "restore_icloud_change_set",
    description: "Restore a previously backed-up change set from _CHANGES_BACKUP.",
    inputSchema: {
      type: "object",
      properties: {
        change_set_id: { type: "string", minLength: 1 },
      },
      required: ["change_set_id"],
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) =>
      fetchOriginJson(env, "/files/ops/restore", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          change_set_id: readString(args.change_set_id, "change_set_id"),
        }),
      }),
  },
  {
    name: "sync_icloud_manual_feedback_events",
    description: "Re-read manual Obsidian feedback signals and persist them as indexed feedback events.",
    inputSchema: {
      type: "object",
      properties: {
        limit: { type: "integer", minimum: 1, maximum: 200 },
      },
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) =>
      fetchOriginJson(env, "/files/ops/manual-feedback/sync", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          limit: readOptionalBoundedInt(args.limit, "limit", 1, 200) ?? 25,
        }),
      }),
  },
  {
    name: "analyze_icloud_duplicates",
    description:
      "Analyze live mirrored files for duplicate candidates and persist indexed duplicate-group proposals.",
    inputSchema: {
      type: "object",
      properties: {
        namespaces: {
          type: "array",
          items: { type: "string", enum: ["google1", "google2", "icloud"] },
          minItems: 1,
        },
        limit: { type: "integer", minimum: 1, maximum: 200 },
      },
      required: ["namespaces"],
      additionalProperties: false,
    },
    annotations: WRITE_ANNOTATIONS,
    outputSchema: GENERIC_OBJECT_SCHEMA,
    handler: async ({ env }, args) =>
      fetchOriginJson(env, "/files/ops/dedupe/analyze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          namespaces: readStringArray(args.namespaces, "namespaces", ["google1", "google2", "icloud"]),
          limit: readOptionalBoundedInt(args.limit, "limit", 1, 200) ?? 25,
        }),
      }),
  },
];

const TOOLS_BY_NAME = new Map(TOOL_DEFINITIONS.map((tool) => [tool.name, tool]));

function listToolsResult(): JsonObject {
  return {
    tools: TOOL_DEFINITIONS.map((tool) => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.inputSchema,
      outputSchema: tool.outputSchema,
      annotations: tool.annotations,
    })),
  };
}

async function handleToolCall(context: ToolContext, args: JsonObject): Promise<JsonObject> {
  const toolName = readString(args.name, "name");
  const tool = TOOLS_BY_NAME.get(toolName);
  if (!tool) {
    throw new Error(`Unknown tool: ${toolName}`);
  }
  const toolArgs = asObject(args.arguments);
  return jsonToolResult(await tool.handler(context, toolArgs));
}

async function handleMcpRequest(request: Request, env: Env): Promise<Response> {
  const body = await request.text();
  let parsed: JsonObject;
  try {
    parsed = JSON.parse(body);
  } catch {
    return mcpError(null, -32700, "Parse error", 400);
  }

  const method = trimString(parsed.method);
  const id = typeof parsed.id === "undefined" ? null : (parsed.id as JsonValue);
  const params = asObject(parsed.params);

  try {
    if (method === "initialize") {
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: MCP_PROTOCOL_VERSION,
          capabilities: {
            tools: {},
          },
          serverInfo: {
            name: SERVER_NAME,
            version: SERVER_VERSION,
          },
        },
      });
    }

    if (method === "notifications/initialized") {
      return new Response(null, { status: 202 });
    }

    if (method === "ping") {
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: {},
      });
    }

    if (method === "tools/list") {
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: listToolsResult(),
      });
    }

    if (method === "tools/call") {
      const result = await handleToolCall({ env, request }, params);
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result,
      });
    }

    return mcpError(id, -32601, `Method not found: ${method}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return jsonResponse({
      jsonrpc: "2.0",
      id,
      result: {
        content: [
          {
            type: "text",
            text: message,
          },
        ],
        isError: true,
      },
    });
  }
}

async function maybeHandleNonMcpRequest(request: Request, env: Env): Promise<Response | null> {
  const url = new URL(request.url);
  const healthPath = getHealthRoute(env);
  const downloadPrefix = `${getDownloadRoute(env)}/`;

  if (url.pathname === "/" || url.pathname === healthPath) {
    return jsonResponse(buildHealthPayload(env, request));
  }

  if (url.pathname.startsWith(downloadPrefix)) {
    if (!(await hasValidWorkerApiToken(request, env))) {
      return unauthorizedResponse();
    }
    return proxyDownload(request, env);
  }

  return null;
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const earlyResponse = await maybeHandleNonMcpRequest(request, env);
    if (earlyResponse) {
      return earlyResponse;
    }

    const url = new URL(request.url);
    if (url.pathname !== getMcpRoute(env)) {
      return new Response("Not found", { status: 404 });
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", {
        status: 405,
        headers: {
          Allow: "POST, DELETE",
        },
      });
    }

    if (!(await hasValidWorkerApiToken(request, env))) {
      return unauthorizedResponse();
    }

    return handleMcpRequest(request, env);
  },
} satisfies ExportedHandler<Env>;
