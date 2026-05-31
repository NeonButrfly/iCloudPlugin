export type Env = {
  ORIGIN_BASE_URL: string;
  ORIGIN_API_TOKEN: string;
  WORKER_API_TOKEN?: string;
  MCP_ROUTE?: string;
  DOWNLOAD_ROUTE_PREFIX?: string;
  HEALTH_ROUTE?: string;
};

export type JsonObject = Record<string, unknown>;

export const WORKER_NAME = "iCloudPlugin Remote MCP";
export const WORKER_VERSION = "0.1.0";

type TimingSafeSubtleCrypto = SubtleCrypto & {
  timingSafeEqual?: (a: BufferSource, b: BufferSource) => boolean;
};

export function buildOriginUrl(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  const normalizedPath = path.startsWith("/") ? path.slice(1) : path;
  return new URL(normalizedPath, normalizedBase).toString();
}

export async function fetchOriginJson(
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

export function timingSafeEqualBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) {
    return false;
  }

  let mismatch = 0;
  for (let index = 0; index < a.length; index += 1) {
    mismatch |= a[index] ^ b[index];
  }
  return mismatch === 0;
}

async function sha256Bytes(value: string): Promise<Uint8Array> {
  return new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
  );
}

export async function hasValidWorkerApiToken(request: Request, env: Env): Promise<boolean> {
  const expectedToken = env.WORKER_API_TOKEN?.trim();
  if (!expectedToken) {
    return true;
  }

  const authorizationHeader = request.headers.get("Authorization") || "";
  const bearerPrefix = "Bearer ";
  if (!authorizationHeader.startsWith(bearerPrefix)) {
    return false;
  }

  const providedToken = authorizationHeader.slice(bearerPrefix.length).trim();
  if (!providedToken) {
    return false;
  }

  const [providedDigest, expectedDigest] = await Promise.all([
    sha256Bytes(providedToken),
    sha256Bytes(expectedToken),
  ]);

  const subtle = crypto.subtle as TimingSafeSubtleCrypto;
  if (typeof subtle.timingSafeEqual !== "function") {
    return timingSafeEqualBytes(providedDigest, expectedDigest);
  }
  return subtle.timingSafeEqual(
    providedDigest as unknown as BufferSource,
    expectedDigest as unknown as BufferSource,
  );
}

export function getAuthMode(env: Env): "worker-api-token" | "origin-only" {
  return env.WORKER_API_TOKEN?.trim() ? "worker-api-token" : "origin-only";
}

export function jsonResponse(payload: JsonObject, status = 200): Response {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "private, no-store",
    },
  });
}

export function unauthorizedResponse(): Response {
  return jsonResponse(
    {
      error: "unauthorized",
      detail: "A valid bearer token is required for this remote MCP server.",
    },
    401,
  );
}

export function buildHealthPayload(env: Env, request: Request): JsonObject {
  const mcpRoute = env.MCP_ROUTE || "/mcp";
  const downloadRoutePrefix = env.DOWNLOAD_ROUTE_PREFIX || "/download";
  const healthRoute = env.HEALTH_ROUTE || "/healthz";
  return {
    status: "ok",
    name: WORKER_NAME,
    version: WORKER_VERSION,
    auth_mode: getAuthMode(env),
    mcp_route: new URL(mcpRoute, request.url).toString(),
    download_route_prefix: new URL(downloadRoutePrefix, request.url).toString(),
    health_route: new URL(healthRoute, request.url).toString(),
    has_origin_base_url: Boolean(env.ORIGIN_BASE_URL?.trim()),
    has_origin_api_token: Boolean(env.ORIGIN_API_TOKEN?.trim()),
  };
}

export function withWorkerDownloadUrl(
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

export async function proxyDownload(request: Request, env: Env): Promise<Response> {
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

export async function maybeHandleNonMcpRequest(
  request: Request,
  env: Env,
): Promise<Response | null> {
  const url = new URL(request.url);
  const mcpRoute = env.MCP_ROUTE || "/mcp";
  const downloadPrefix = env.DOWNLOAD_ROUTE_PREFIX || "/download";
  const healthRoute = env.HEALTH_ROUTE || "/healthz";

  if (url.pathname === healthRoute) {
    return jsonResponse(buildHealthPayload(env, request));
  }

  if (url.pathname.startsWith(`${downloadPrefix}/`)) {
    if (!(await hasValidWorkerApiToken(request, env))) {
      return unauthorizedResponse();
    }
    return proxyDownload(request, env);
  }

  if (url.pathname === "/") {
    return jsonResponse(buildHealthPayload(env, request));
  }

  if (url.pathname === mcpRoute && !(await hasValidWorkerApiToken(request, env))) {
    return unauthorizedResponse();
  }

  return null;
}
