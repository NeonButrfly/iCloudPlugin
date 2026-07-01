#!/usr/bin/env node

import process from "node:process";
import { pathToFileURL } from "node:url";

const DEFAULT_PUBLIC_BASE_URL = "https://icloudplugin-remote-mcp.kaymayers9.workers.dev";
const DEFAULT_ORIGIN_BASE_URL = "https://clouddrive.neonbutterfly.net";

function trim(value) {
  return (value || "").trim();
}

export function buildPlan(env = process.env) {
  const publicBaseUrl = trim(env.REMOTE_MCP_PUBLIC_BASE_URL) || DEFAULT_PUBLIC_BASE_URL;
  const originBaseUrl = trim(env.ORIGIN_BASE_URL) || DEFAULT_ORIGIN_BASE_URL;
  const workerApiTokenConfigured = Boolean(trim(env.WORKER_API_TOKEN));

  return {
    connector_name: "iCloudPlugin Remote MCP",
    connector_mode: "ChatGPT Developer mode",
    worker_base_url: publicBaseUrl,
    mcp_url: new URL("/mcp", `${publicBaseUrl.replace(/\/+$/, "")}/`).toString(),
    health_url: new URL("/healthz", `${publicBaseUrl.replace(/\/+$/, "")}/`).toString(),
    origin_base_url: originBaseUrl,
    worker_auth_mode: workerApiTokenConfigured ? "worker-api-token" : "origin-only",
    recommended_worker_auth_mode: "origin-only",
    required_worker_secrets: ["ORIGIN_BASE_URL", "ORIGIN_API_TOKEN"],
    optional_worker_secrets: ["WORKER_API_TOKEN"],
    recommendation: workerApiTokenConfigured
      ? "Unset WORKER_API_TOKEN before ChatGPT developer-mode use so ChatGPT does not need a custom bearer token."
      : "Worker auth is already aligned for ChatGPT developer-mode use.",
    chatgpt_steps: [
      "Open ChatGPT and enable Developer mode if needed.",
      "Open Settings -> Apps and create an app for the remote MCP server.",
      "Use the MCP URL from this plan.",
      "Choose No Authentication for the worker-facing connection when the Worker is in origin-only mode.",
      "Start a new chat and add the app from Developer mode.",
    ],
    official_docs: {
      connect_from_chatgpt: "https://developers.openai.com/apps-sdk/deploy/connect-chatgpt",
      auth: "https://developers.openai.com/apps-sdk/build/auth",
      developer_mode: "https://developers.openai.com/api/docs/guides/developer-mode",
    },
  };
}

function printPlan(plan) {
  console.log("ChatGPT developer-mode plan for iCloudPlugin Remote MCP");
  console.log();
  console.log(`Worker base URL: ${plan.worker_base_url}`);
  console.log(`MCP URL: ${plan.mcp_url}`);
  console.log(`Health URL: ${plan.health_url}`);
  console.log(`Origin base URL: ${plan.origin_base_url}`);
  console.log(`Current worker auth mode: ${plan.worker_auth_mode}`);
  console.log(`Recommended worker auth mode: ${plan.recommended_worker_auth_mode}`);
  console.log();
  console.log(plan.recommendation);
  console.log();
  console.log("Required Worker secrets:");
  for (const name of plan.required_worker_secrets) {
    console.log(`- ${name}`);
  }
  console.log("Optional Worker secrets:");
  for (const name of plan.optional_worker_secrets) {
    console.log(`- ${name}`);
  }
  console.log();
  console.log("ChatGPT steps:");
  for (const [index, step] of plan.chatgpt_steps.entries()) {
    console.log(`${index + 1}. ${step}`);
  }
  console.log();
  console.log("Official docs:");
  console.log(`- Connect from ChatGPT: ${plan.official_docs.connect_from_chatgpt}`);
  console.log(`- Auth: ${plan.official_docs.auth}`);
  console.log(`- Developer mode: ${plan.official_docs.developer_mode}`);
}

async function main() {
  const args = new Set(process.argv.slice(2));
  const plan = buildPlan();
  if (args.has("--json")) {
    console.log(JSON.stringify(plan, null, 2));
    return;
  }
  printPlan(plan);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
