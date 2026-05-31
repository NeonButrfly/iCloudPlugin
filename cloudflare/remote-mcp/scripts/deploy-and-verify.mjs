#!/usr/bin/env node

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";

const WORKER_ROOT = path.resolve(import.meta.dirname, "..");
const DEFAULT_MCP_ROUTE = "/mcp";
const DEFAULT_DOWNLOAD_ROUTE_PREFIX = "/download";
const DEFAULT_HEALTH_ROUTE = "/healthz";

function printHelp() {
  console.log(`Usage: node scripts/deploy-and-verify.mjs [options]

Deploy the Cloudflare remote MCP Worker and verify its public health surface.

Options:
  --plan                Print the derived deployment and verification plan without deploying
  --dry-run             Pass --dry-run through to wrangler deploy
  --sync-secrets        Push Worker secrets with wrangler before deploy
  --secrets-file <path> Load Worker secret values from a .env-style file before deploy
  --skip-health-check   Stop after deploy; do not call the public health endpoint
  --base-url <url>      Override the public Worker base URL used for verification
  --health-url <url>    Override the health URL directly
  --json                Print the final summary as JSON
  --help                Show this help text

Environment:
  ORIGIN_BASE_URL             Required by the Worker
  ORIGIN_API_TOKEN            Required by the Worker
  WORKER_API_TOKEN            Optional client-to-Worker bearer token bootstrap
  REMOTE_MCP_PUBLIC_BASE_URL  Optional public base URL for post-deploy verification
  CLOUDFLARE_API_TOKEN        Required for non-interactive wrangler deploys unless Wrangler is already logged in
`);
}

function parseArgs(argv) {
  const options = {
    plan: false,
    dryRun: false,
    syncSecrets: false,
    secretsFile: "",
    skipHealthCheck: false,
    baseUrl: "",
    healthUrl: "",
    json: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    switch (arg) {
      case "--plan":
        options.plan = true;
        break;
      case "--dry-run":
        options.dryRun = true;
        break;
      case "--sync-secrets":
        options.syncSecrets = true;
        break;
      case "--secrets-file":
        options.secretsFile = argv[index + 1] || "";
        index += 1;
        break;
      case "--skip-health-check":
        options.skipHealthCheck = true;
        break;
      case "--base-url":
        options.baseUrl = argv[index + 1] || "";
        index += 1;
        break;
      case "--health-url":
        options.healthUrl = argv[index + 1] || "";
        index += 1;
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

function getTrimmedEnv(name) {
  return (process.env[name] || "").trim();
}

function hasWranglerLoginMaterial() {
  const home = process.env.USERPROFILE || process.env.HOME || "";
  if (!home) {
    return false;
  }
  return existsSync(path.join(home, ".wrangler", "config", "default.toml"));
}

function deriveRoutes() {
  return {
    mcpRoute: getTrimmedEnv("MCP_ROUTE") || DEFAULT_MCP_ROUTE,
    downloadRoutePrefix:
      getTrimmedEnv("DOWNLOAD_ROUTE_PREFIX") || DEFAULT_DOWNLOAD_ROUTE_PREFIX,
    healthRoute: getTrimmedEnv("HEALTH_ROUTE") || DEFAULT_HEALTH_ROUTE,
  };
}

function trimTrailingSlash(value) {
  return value.replace(/\/+$/, "");
}

function buildUrl(baseUrl, route) {
  return new URL(route, `${trimTrailingSlash(baseUrl)}/`).toString();
}

function summarizeConfig(options) {
  const routes = deriveRoutes();
  const secretInputs = resolveSecretInputs(options);
  const baseUrl =
    options.baseUrl ||
    getTrimmedEnv("REMOTE_MCP_PUBLIC_BASE_URL") ||
    "";
  const healthUrl =
    options.healthUrl || (baseUrl ? buildUrl(baseUrl, routes.healthRoute) : "");

  return {
    workerName: "icloudplugin-remote-mcp",
    workerRoot: WORKER_ROOT,
    secretSyncEnabled: options.syncSecrets,
    secretsFile: options.secretsFile || null,
    availableSecretKeys: Object.keys(secretInputs),
    hasOriginBaseUrl: Boolean(getTrimmedEnv("ORIGIN_BASE_URL")),
    hasOriginApiToken: Boolean(getTrimmedEnv("ORIGIN_API_TOKEN")),
    authMode: getTrimmedEnv("WORKER_API_TOKEN") ? "worker-api-token" : "origin-only",
    hasCloudflareApiToken: Boolean(getTrimmedEnv("CLOUDFLARE_API_TOKEN")),
    hasWranglerLogin: hasWranglerLoginMaterial(),
    baseUrl: baseUrl || null,
    healthUrl: healthUrl || null,
    mcpUrl: baseUrl ? buildUrl(baseUrl, routes.mcpRoute) : null,
    downloadExampleUrl: baseUrl
      ? buildUrl(baseUrl, `${routes.downloadRoutePrefix}/123`)
      : null,
    routes,
    dryRun: options.dryRun,
    skipHealthCheck: options.skipHealthCheck,
  };
}

function ensureRequiredOriginEnv(secretInputs) {
  const missing = [];
  if (!secretInputs.ORIGIN_BASE_URL) {
    missing.push("ORIGIN_BASE_URL");
  }
  if (!secretInputs.ORIGIN_API_TOKEN) {
    missing.push("ORIGIN_API_TOKEN");
  }
  if (missing.length) {
    throw new Error(`Missing required Worker secrets/env: ${missing.join(", ")}`);
  }
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

function resolveSecretInputs(options) {
  const secrets = {};
  const candidateNames = ["ORIGIN_BASE_URL", "ORIGIN_API_TOKEN", "WORKER_API_TOKEN"];
  for (const name of candidateNames) {
    const value = getTrimmedEnv(name);
    if (value) {
      secrets[name] = value;
    }
  }

  if (options.secretsFile) {
    const fileSecrets = parseEnvStyleFile(options.secretsFile);
    for (const name of candidateNames) {
      const value = (fileSecrets[name] || "").trim();
      if (value) {
        secrets[name] = value;
      }
    }
  }

  return secrets;
}

function ensureSecretsAvailableForSync(secretInputs) {
  const required = ["ORIGIN_BASE_URL", "ORIGIN_API_TOKEN"];
  const missing = required.filter((name) => !secretInputs[name]);
  if (missing.length) {
    throw new Error(
      `Secret sync requires these values before deploy: ${missing.join(", ")}.`,
    );
  }
}

function ensureDeployAuthAvailable() {
  if (getTrimmedEnv("CLOUDFLARE_API_TOKEN")) {
    return;
  }
  if (hasWranglerLoginMaterial()) {
    return;
  }
  throw new Error(
    "Cloudflare deploy auth is unavailable. Set CLOUDFLARE_API_TOKEN or log in with Wrangler first.",
  );
}

function runCommand(command, args, { cwd, env }) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      shell: process.platform === "win32",
    });
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
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`${command} ${args.join(" ")} failed with exit code ${code}`));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

function extractWorkersDevBaseUrl(output) {
  const match = output.match(/https:\/\/[^\s]+\.workers\.dev/);
  return match ? trimTrailingSlash(match[0]) : "";
}

async function verifyHealth(healthUrl) {
  const response = await fetch(healthUrl, {
    headers: {
      Accept: "application/json",
    },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Health check failed (${response.status}): ${text}`);
  }
  const payload = JSON.parse(text);
  if (payload.status !== "ok") {
    throw new Error(`Health payload was not ok: ${text}`);
  }
  if (!payload.has_origin_base_url || !payload.has_origin_api_token) {
    throw new Error(`Health payload reported missing origin configuration: ${text}`);
  }
  return payload;
}

async function syncSecrets(secretInputs) {
  const tempDir = mkdtempSync(path.join(tmpdir(), "icloudplugin-remote-mcp-"));
  const payloadPath = path.join(tempDir, "wrangler-secrets.json");
  try {
    writeFileSync(payloadPath, JSON.stringify(secretInputs, null, 2), "utf8");
    await runCommand(
      process.platform === "win32" ? "npx.cmd" : "npx",
      ["wrangler", "secret", "bulk", payloadPath],
      {
        cwd: WORKER_ROOT,
        env: {
          ...process.env,
        },
      },
    );
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const plan = summarizeConfig(options);
  if (options.plan) {
    console.log(options.json ? JSON.stringify(plan, null, 2) : plan);
    return;
  }

  const secretInputs = resolveSecretInputs(options);
  ensureRequiredOriginEnv(secretInputs);
  ensureDeployAuthAvailable();

  if (options.syncSecrets) {
    ensureSecretsAvailableForSync(secretInputs);
    await syncSecrets(secretInputs);
  }

  const deployArgs = ["wrangler", "deploy", "--keep-vars"];
  if (options.dryRun) {
    deployArgs.push("--dry-run");
  }

  const { stdout, stderr } = await runCommand(
    process.platform === "win32" ? "npx.cmd" : "npx",
    deployArgs,
    {
      cwd: WORKER_ROOT,
      env: {
        ...process.env,
      },
    },
  );

  const derivedBaseUrl =
    options.baseUrl ||
    getTrimmedEnv("REMOTE_MCP_PUBLIC_BASE_URL") ||
    extractWorkersDevBaseUrl(`${stdout}\n${stderr}`);
  const routes = deriveRoutes();
  const healthUrl =
    options.healthUrl ||
    (derivedBaseUrl ? buildUrl(derivedBaseUrl, routes.healthRoute) : "");

  const summary = {
    ...plan,
    baseUrl: derivedBaseUrl || null,
    healthUrl: healthUrl || null,
    mcpUrl: derivedBaseUrl ? buildUrl(derivedBaseUrl, routes.mcpRoute) : null,
    downloadExampleUrl: derivedBaseUrl
      ? buildUrl(derivedBaseUrl, `${routes.downloadRoutePrefix}/123`)
      : null,
    deployMode: options.dryRun ? "dry-run" : "deploy",
  };

  if (!options.skipHealthCheck && !options.dryRun) {
    if (!healthUrl) {
      throw new Error(
        "The Worker deployed, but no public base URL was available for health verification. Set REMOTE_MCP_PUBLIC_BASE_URL or pass --base-url.",
      );
    }
    summary.health = await verifyHealth(healthUrl);
  }

  console.log(options.json ? JSON.stringify(summary, null, 2) : summary);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
