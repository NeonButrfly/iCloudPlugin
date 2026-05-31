#!/usr/bin/env node

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const WORKER_ROOT = path.resolve(import.meta.dirname, "..");
export const DEFAULT_REPO = "NeonButrfly/iCloudPlugin";
export const SECRET_MAPPINGS = [
  { sourceName: "CLOUDFLARE_API_TOKEN", targetName: "CLOUDFLARE_API_TOKEN", required: true, kind: "secret" },
  { sourceName: "ORIGIN_BASE_URL", targetName: "REMOTE_MCP_ORIGIN_BASE_URL", required: true, kind: "secret" },
  { sourceName: "ORIGIN_API_TOKEN", targetName: "REMOTE_MCP_ORIGIN_API_TOKEN", required: true, kind: "secret" },
  { sourceName: "WORKER_API_TOKEN", targetName: "REMOTE_MCP_WORKER_API_TOKEN", required: false, kind: "secret" },
  { sourceName: "REMOTE_MCP_PUBLIC_BASE_URL", targetName: "REMOTE_MCP_PUBLIC_BASE_URL", required: false, kind: "variable" },
  { sourceName: "REMOTE_MCP_VERIFY_HEADERS_JSON", targetName: "REMOTE_MCP_VERIFY_HEADERS_JSON", required: false, kind: "secret" },
  { sourceName: "CF_ACCESS_CLIENT_ID", targetName: "CF_ACCESS_CLIENT_ID", required: false, kind: "secret" },
  { sourceName: "CF_ACCESS_CLIENT_SECRET", targetName: "CF_ACCESS_CLIENT_SECRET", required: false, kind: "secret" },
  { sourceName: "CF_ACCESS_TOKEN", targetName: "CF_ACCESS_TOKEN", required: false, kind: "secret" },
];

function printHelp() {
  console.log(`Usage: node scripts/bootstrap-github-secrets.mjs [options]

Bootstrap the GitHub repo secrets/variables required by the remote MCP
deploy workflow.

Options:
  --repo <owner/name>       GitHub repo to target (default: ${DEFAULT_REPO})
  --secrets-file <path>     Load source values from a .env-style file
  --public-base-url <url>   Override REMOTE_MCP_PUBLIC_BASE_URL for the plan/apply
  --apply                   Write repo secrets/variables with gh instead of only printing a plan
  --json                    Print the plan/apply summary as JSON
  --help                    Show this help text
`);
}

export function parseArgs(argv) {
  const options = {
    repo: DEFAULT_REPO,
    secretsFile: "",
    publicBaseUrl: "",
    apply: false,
    json: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    switch (arg) {
      case "--repo":
        options.repo = argv[index + 1] || DEFAULT_REPO;
        index += 1;
        break;
      case "--secrets-file":
        options.secretsFile = argv[index + 1] || "";
        index += 1;
        break;
      case "--public-base-url":
        options.publicBaseUrl = argv[index + 1] || "";
        index += 1;
        break;
      case "--apply":
        options.apply = true;
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

function collectSourceValues(options, env = process.env) {
  const fileValues = options.secretsFile ? parseEnvStyleFile(options.secretsFile) : {};
  const sources = { ...fileValues };
  for (const mapping of SECRET_MAPPINGS) {
    const envValue = trim(env[mapping.sourceName]);
    if (envValue) {
      sources[mapping.sourceName] = envValue;
    }
  }
  if (trim(options.publicBaseUrl)) {
    sources.REMOTE_MCP_PUBLIC_BASE_URL = trim(options.publicBaseUrl);
  }
  return sources;
}

export function resolveBootstrapPlan(options, env = process.env) {
  const sources = collectSourceValues(options, env);
  const entries = SECRET_MAPPINGS.map((mapping) => {
    const value = trim(sources[mapping.sourceName]);
    return {
      source_name: mapping.sourceName,
      target_name: mapping.targetName,
      kind: mapping.kind,
      required: mapping.required,
      present: Boolean(value),
      value_length: value.length,
    };
  });

  const missingRequired = entries
    .filter((entry) => entry.required && !entry.present)
    .map((entry) => entry.target_name);

  return {
    repo: trim(options.repo) || DEFAULT_REPO,
    secrets_file: options.secretsFile || null,
    apply: Boolean(options.apply),
    entries,
    missing_required: missingRequired,
    can_apply: missingRequired.length === 0,
  };
}

function runGhCommand(args, stdinValue) {
  return new Promise((resolve, reject) => {
    const child = spawn("gh", args, {
      cwd: WORKER_ROOT,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
      shell: process.platform === "win32",
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`gh ${args.join(" ")} failed with exit code ${code}: ${stderr}`));
        return;
      }
      resolve(undefined);
    });
    child.stdin.write(stdinValue);
    child.stdin.end();
  });
}

async function applyBootstrapPlan(plan, options, env = process.env) {
  if (!plan.can_apply) {
    throw new Error(`Missing required values for apply: ${plan.missing_required.join(", ")}`);
  }

  const sources = collectSourceValues(options, env);
  const applied = [];
  for (const entry of plan.entries) {
    if (!entry.present) {
      continue;
    }
    const value = trim(sources[entry.source_name]);
    const args =
      entry.kind === "secret"
        ? ["secret", "set", entry.target_name, "--repo", plan.repo]
        : ["variable", "set", entry.target_name, "--repo", plan.repo];
    await runGhCommand(args, value);
    applied.push({ target_name: entry.target_name, kind: entry.kind });
  }

  return { ...plan, applied };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const plan = resolveBootstrapPlan(options);
  if (!options.apply) {
    console.log(options.json ? JSON.stringify(plan, null, 2) : plan);
    return;
  }

  const applied = await applyBootstrapPlan(plan, options);
  console.log(options.json ? JSON.stringify(applied, null, 2) : applied);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
