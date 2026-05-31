#!/usr/bin/env node

import process from "node:process";
import { pathToFileURL } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

export const DEFAULT_MCP_ROUTE = "/mcp";
export const DEFAULT_HEALTH_ROUTE = "/healthz";
export const DEFAULT_EXPECTED_TOOLS = [
  "search_icloud_files",
  "search_icloud_notes_and_files",
  "get_icloud_system_status",
  "get_icloud_file",
  "get_icloud_file_excerpt",
  "get_icloud_note",
  "get_icloud_source_reference",
  "get_icloud_file_bundle",
  "refresh_icloud_index",
];

function printHelp() {
  console.log(`Usage: node scripts/verify-mcp-tools.mjs [options]

Connect to the remote MCP endpoint over Streamable HTTP, list tools, and call
one probe tool to verify the Worker is usable by a real MCP client.

Options:
  --mcp-url <url>           Full MCP endpoint URL (for example https://worker/mcp)
  --base-url <url>          Public Worker base URL; /mcp and /healthz are derived
  --token <token>           Bearer token for client-to-Worker auth
  --probe-tool <name>       Tool to call after listTools (default: get_icloud_system_status)
  --probe-args <json>       JSON arguments for the probe tool (default: {})
  --expect-tools <csv>      Comma-separated expected tool names
  --skip-health             Skip the preflight /healthz fetch
  --json                    Print the final summary as JSON
  --help                    Show this help text

Environment:
  REMOTE_MCP_MCP_URL        Optional default MCP endpoint URL
  REMOTE_MCP_PUBLIC_BASE_URL Optional Worker base URL used to derive /mcp and /healthz
  WORKER_API_TOKEN          Optional default bearer token for Worker auth
  MCP_ROUTE                 Optional route override when deriving from --base-url
  HEALTH_ROUTE              Optional route override when deriving from --base-url
`);
}

export function parseArgs(argv) {
  const options = {
    mcpUrl: "",
    baseUrl: "",
    token: "",
    probeTool: "get_icloud_system_status",
    probeArgsRaw: "{}",
    expectToolsCsv: "",
    skipHealth: false,
    json: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    switch (arg) {
      case "--mcp-url":
        options.mcpUrl = argv[index + 1] || "";
        index += 1;
        break;
      case "--base-url":
        options.baseUrl = argv[index + 1] || "";
        index += 1;
        break;
      case "--token":
        options.token = argv[index + 1] || "";
        index += 1;
        break;
      case "--probe-tool":
        options.probeTool = argv[index + 1] || "";
        index += 1;
        break;
      case "--probe-args":
        options.probeArgsRaw = argv[index + 1] || "";
        index += 1;
        break;
      case "--expect-tools":
        options.expectToolsCsv = argv[index + 1] || "";
        index += 1;
        break;
      case "--skip-health":
        options.skipHealth = true;
        break;
      case "--json":
        options.json = true;
        break;
      case "--help":
      case "-h":
        printHelp();
        process.exit(0);
        break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }

  return options;
}

function trim(value) {
  return (value || "").trim();
}

function trimTrailingSlash(value) {
  return value.replace(/\/+$/, "");
}

function routeValue(name, fallback) {
  return trim(process.env[name]) || fallback;
}

export function buildDerivedUrls(baseUrl) {
  const normalizedBase = trimTrailingSlash(baseUrl);
  const mcpRoute = routeValue("MCP_ROUTE", DEFAULT_MCP_ROUTE);
  const healthRoute = routeValue("HEALTH_ROUTE", DEFAULT_HEALTH_ROUTE);
  return {
    mcpUrl: new URL(mcpRoute, `${normalizedBase}/`).toString(),
    healthUrl: new URL(healthRoute, `${normalizedBase}/`).toString(),
  };
}

export function parseJsonObject(rawValue, label) {
  let parsed;
  try {
    parsed = JSON.parse(rawValue);
  } catch (error) {
    throw new Error(
      `${label} must be valid JSON: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must decode to a JSON object`);
  }
  return parsed;
}

export function buildAuthHeaders(token) {
  const trimmedToken = trim(token);
  if (!trimmedToken) {
    return {};
  }
  return {
    Authorization: `Bearer ${trimmedToken}`,
  };
}

export function summarizeProbeResult(result) {
  const contentPreview = Array.isArray(result?.content)
    ? result.content
        .map((item) => {
          if (!item || typeof item !== "object") {
            return String(item);
          }
          if (item.type === "text") {
            return typeof item.text === "string" ? item.text.slice(0, 400) : "";
          }
          return `[${item.type}]`;
        })
        .filter(Boolean)
    : [];

  return {
    isError: Boolean(result?.isError),
    structuredContent:
      result && typeof result === "object" && "structuredContent" in result
        ? result.structuredContent
        : null,
    contentPreview,
  };
}

export function resolveConfig(options, env = process.env) {
  const explicitMcpUrl = trim(options.mcpUrl) || trim(env.REMOTE_MCP_MCP_URL);
  const explicitBaseUrl = trim(options.baseUrl) || trim(env.REMOTE_MCP_PUBLIC_BASE_URL);

  let mcpUrl = explicitMcpUrl;
  let healthUrl = "";
  if (!mcpUrl) {
    if (!explicitBaseUrl) {
      throw new Error(
        "Provide --mcp-url, --base-url, REMOTE_MCP_MCP_URL, or REMOTE_MCP_PUBLIC_BASE_URL.",
      );
    }
    const derived = buildDerivedUrls(explicitBaseUrl);
    mcpUrl = derived.mcpUrl;
    healthUrl = derived.healthUrl;
  } else if (explicitBaseUrl) {
    healthUrl = buildDerivedUrls(explicitBaseUrl).healthUrl;
  }

  const probeTool = trim(options.probeTool) || "get_icloud_system_status";
  const probeArgs = parseJsonObject(options.probeArgsRaw || "{}", "--probe-args");
  const expectedTools = trim(options.expectToolsCsv)
    ? trim(options.expectToolsCsv)
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean)
    : [...DEFAULT_EXPECTED_TOOLS];

  return {
    mcpUrl,
    healthUrl,
    token: trim(options.token) || trim(env.WORKER_API_TOKEN),
    probeTool,
    probeArgs,
    expectedTools,
    skipHealth: Boolean(options.skipHealth),
    json: Boolean(options.json),
  };
}

export async function fetchHealthSummary(config) {
  if (config.skipHealth || !config.healthUrl) {
    return null;
  }

  const response = await fetch(config.healthUrl, {
    headers: {
      Accept: "application/json",
      ...buildAuthHeaders(config.token),
    },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Health preflight failed (${response.status}): ${text}`);
  }
  const payload = JSON.parse(text);
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Health preflight returned a non-object payload");
  }
  return payload;
}

export async function runVerification(config) {
  const health = await fetchHealthSummary(config);
  const requestHeaders = buildAuthHeaders(config.token);
  const client = new Client({
    name: "icloudplugin-remote-mcp-verifier",
    version: "0.1.0",
  });
  const transport = new StreamableHTTPClientTransport(new URL(config.mcpUrl), {
    requestInit: {
      headers: requestHeaders,
    },
  });

  try {
    await client.connect(transport);
    const toolList = await client.listTools();
    const availableTools = toolList.tools.map((tool) => tool.name);
    const missingTools = config.expectedTools.filter((tool) => !availableTools.includes(tool));
    if (missingTools.length > 0) {
      throw new Error(`Remote MCP is missing expected tools: ${missingTools.join(", ")}`);
    }

    const probeResult = await client.callTool({
      name: config.probeTool,
      arguments: config.probeArgs,
    });
    if (probeResult.isError) {
      throw new Error(`Probe tool ${config.probeTool} returned an error result`);
    }

    return {
      status: "ok",
      mcp_url: config.mcpUrl,
      health_url: config.healthUrl || null,
      health,
      tool_count: availableTools.length,
      available_tools: availableTools,
      expected_tools: config.expectedTools,
      probe_tool: config.probeTool,
      probe_args: config.probeArgs,
      probe_result: summarizeProbeResult(probeResult),
    };
  } finally {
    await transport.close().catch(() => undefined);
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const config = resolveConfig(options);
  const summary = await runVerification(config);
  if (config.json) {
    console.log(JSON.stringify(summary, null, 2));
    return;
  }
  console.log(summary);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
