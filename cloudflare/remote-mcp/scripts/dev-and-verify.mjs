#!/usr/bin/env node

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";
import { resolveConfig as resolveMcpVerifyConfig, runVerification } from "./verify-mcp-tools.mjs";

const WORKER_ROOT = path.resolve(import.meta.dirname, "..");
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8788;
const DEFAULT_STARTUP_TIMEOUT_MS = 30000;

function printHelp() {
  console.log(`Usage: node scripts/dev-and-verify.mjs [options]

Start the Cloudflare Worker locally with wrangler dev, then verify its /healthz
and /mcp routes like a real remote MCP client.

Options:
  --host <host>             Local listen address for wrangler dev (default: ${DEFAULT_HOST})
  --port <port>             Port to bind wrangler dev (default: ${DEFAULT_PORT})
  --secrets-file <path>     Load Worker env values from a .env-style file before launch
  --verify-header <h>       Extra header for the MCP verifier, repeatable (name:value)
  --startup-timeout-ms <n>  Milliseconds to wait for /healthz (default: ${DEFAULT_STARTUP_TIMEOUT_MS})
  --skip-health-check       Skip the /healthz readiness check
  --skip-mcp-check          Skip the /mcp smoke verification step
  --json                    Print the final summary as JSON
  --help                    Show this help text

Environment:
  ORIGIN_BASE_URL             Required by the Worker
  ORIGIN_API_TOKEN            Required by the Worker
  WORKER_API_TOKEN            Optional client-to-Worker bearer token bootstrap
  REMOTE_MCP_VERIFY_HEADERS_JSON Optional JSON object of extra headers for MCP smoke verification
  CF_ACCESS_CLIENT_ID         Optional Cloudflare Access client id for MCP smoke verification
  CF_ACCESS_CLIENT_SECRET     Optional Cloudflare Access client secret for MCP smoke verification
  CF_ACCESS_TOKEN             Optional Cloudflare Access token for MCP smoke verification
`);
}

function parseArgs(argv) {
  const options = {
    host: DEFAULT_HOST,
    port: DEFAULT_PORT,
    secretsFile: "",
    verifyHeaders: [],
    startupTimeoutMs: DEFAULT_STARTUP_TIMEOUT_MS,
    skipHealthCheck: false,
    skipMcpCheck: false,
    json: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    switch (arg) {
      case "--host":
        options.host = argv[index + 1] || DEFAULT_HOST;
        index += 1;
        break;
      case "--port":
        options.port = Number.parseInt(argv[index + 1] || "", 10) || DEFAULT_PORT;
        index += 1;
        break;
      case "--secrets-file":
        options.secretsFile = argv[index + 1] || "";
        index += 1;
        break;
      case "--verify-header":
        options.verifyHeaders.push(argv[index + 1] || "");
        index += 1;
        break;
      case "--startup-timeout-ms":
        options.startupTimeoutMs =
          Number.parseInt(argv[index + 1] || "", 10) || DEFAULT_STARTUP_TIMEOUT_MS;
        index += 1;
        break;
      case "--skip-health-check":
        options.skipHealthCheck = true;
        break;
      case "--skip-mcp-check":
        options.skipMcpCheck = true;
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

function parseEnvStyleFile(filePath) {
  const resolvedPath = path.resolve(WORKER_ROOT, filePath);
  const parsed = {};
  const raw = readFileSync(resolvedPath, "utf8");
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
      continue;
    }
    const [rawKey, ...rest] = trimmed.split("=");
    const key = rawKey.trim();
    const value = rest.join("=").trim();
    if (!key) {
      continue;
    }
    parsed[key] = value.replace(/^['"]|['"]$/g, "");
  }
  return parsed;
}

function serializeEnvStyleFile(values) {
  return Object.entries(values)
    .map(([name, value]) => `${name}=${value}`)
    .join("\n");
}

function buildWorkerEnv(options) {
  const env = { ...process.env };
  if (options.secretsFile) {
    const fileEnv = parseEnvStyleFile(options.secretsFile);
    for (const [name, value] of Object.entries(fileEnv)) {
      if (trim(value)) {
        env[name] = value;
      }
    }
  }
  return env;
}

function ensureRequiredWorkerEnv(env) {
  const missing = [];
  if (!trim(env.ORIGIN_BASE_URL)) {
    missing.push("ORIGIN_BASE_URL");
  }
  if (!trim(env.ORIGIN_API_TOKEN)) {
    missing.push("ORIGIN_API_TOKEN");
  }
  if (missing.length > 0) {
    throw new Error(
      `Missing required Worker env for local dev verification: ${missing.join(", ")}`,
    );
  }
}

function buildBaseUrl(options) {
  return `http://${options.host}:${options.port}`;
}

async function waitForHealth(healthUrl, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "not started";

  while (Date.now() < deadline) {
    try {
      const response = await fetch(healthUrl, {
        headers: {
          Accept: "application/json",
        },
      });
      const text = await response.text();
      if (response.ok) {
        const payload = JSON.parse(text);
        if (payload.status === "ok") {
          return payload;
        }
        lastError = `health payload not ok: ${text}`;
      } else {
        lastError = `health status ${response.status}: ${text}`;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }

    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  throw new Error(`Timed out waiting for local Worker health: ${lastError}`);
}

function createTempEnvFile(env) {
  const tempDir = mkdtempSync(path.join(tmpdir(), "icloudplugin-remote-mcp-dev-"));
  const envPath = path.join(tempDir, ".env");
  writeFileSync(envPath, `${serializeEnvStyleFile(buildDevVarsPayload(env))}\n`, "utf8");
  return {
    envPath,
    cleanup() {
      rmSync(tempDir, { recursive: true, force: true });
    },
  };
}

function spawnWranglerDev(options, env, envFilePath) {
  return spawn(
    process.platform === "win32" ? "npx.cmd" : "npx",
    [
      "wrangler",
      "dev",
      "--ip",
      options.host,
      "--port",
      String(options.port),
      "--env-file",
      envFilePath,
    ],
    {
      cwd: WORKER_ROOT,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      shell: process.platform === "win32",
    },
  );
}

function buildDevVarsPayload(env) {
  const payload = {};
  for (const name of [
    "ORIGIN_BASE_URL",
    "ORIGIN_API_TOKEN",
    "WORKER_API_TOKEN",
    "REMOTE_MCP_PUBLIC_BASE_URL",
    "REMOTE_MCP_VERIFY_HEADERS_JSON",
    "CF_ACCESS_CLIENT_ID",
    "CF_ACCESS_CLIENT_SECRET",
    "CF_ACCESS_TOKEN",
  ]) {
    const value = trim(env[name]);
    if (value) {
      payload[name] = value;
    }
  }
  return payload;
}

async function stopProcess(child) {
  if (child.exitCode !== null) {
    return;
  }

  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
        shell: true,
      });
      killer.once("exit", () => resolve(undefined));
      setTimeout(() => resolve(undefined), 5000);
    });
    return;
  }

  await new Promise((resolve) => {
    const finish = () => resolve(undefined);
    child.once("exit", finish);
    child.kill();
    setTimeout(() => {
      if (child.exitCode === null) {
        child.kill("SIGKILL");
      }
      resolve(undefined);
    }, 5000);
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const env = buildWorkerEnv(options);
  ensureRequiredWorkerEnv(env);

  const baseUrl = buildBaseUrl(options);
  const healthUrl = `${baseUrl}/healthz`;
  const tempEnvFile = createTempEnvFile(env);
  const child = spawnWranglerDev(options, env, tempEnvFile.envPath);
  let stdout = "";
  let stderr = "";

  child.stdout.on("data", (chunk) => {
    stdout += chunk.toString();
    process.stdout.write(chunk);
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
    process.stderr.write(chunk);
  });

  try {
    let health = null;
    if (!options.skipHealthCheck) {
      health = await waitForHealth(healthUrl, options.startupTimeoutMs);
    }

    let mcp = null;
    if (!options.skipMcpCheck) {
      const config = resolveMcpVerifyConfig(
        {
          mcpUrl: "",
          baseUrl,
          token: "",
          probeTool: "get_icloud_system_status",
          probeArgsRaw: "{}",
          expectToolsCsv: "",
          headers: options.verifyHeaders || [],
          skipHealth: true,
          json: false,
        },
        env,
      );
      mcp = await runVerification(config);
    }

    const summary = {
      status: "ok",
      baseUrl,
      healthUrl,
      health,
      mcp,
    };
    console.log(options.json ? JSON.stringify(summary, null, 2) : summary);
  } finally {
    await stopProcess(child);
    tempEnvFile.cleanup();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
