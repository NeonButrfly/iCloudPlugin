#!/usr/bin/env node

import process from "node:process";

function printHelp() {
  console.log(`Usage: node scripts/print-access-bootstrap.mjs

Print Cloudflare Access bootstrap commands for the remote MCP Worker.

Environment:
  CLOUDFLARE_ACCOUNT_ID           Required Cloudflare account id
  REMOTE_MCP_PUBLIC_BASE_URL      Required worker base URL, for example:
                                  https://icloudplugin-remote-mcp.<subdomain>.workers.dev
  REMOTE_MCP_ACCESS_APP_NAME      Optional Access app name
  ACCESS_ALLOWED_EMAILS           Optional comma-separated allowlist emails
  ACCESS_SERVICE_TOKEN_NAME       Optional service token name
  ACCESS_SESSION_DURATION         Optional session duration (default: 24h)
`);
}

function getTrimmedEnv(name, fallback = "") {
  return (process.env[name] || fallback).trim();
}

function requireEnv(name) {
  const value = getTrimmedEnv(name);
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function escapeSingleQuotes(value) {
  return value.replace(/'/g, `'\"'\"'`);
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    printHelp();
    return;
  }

  const accountId = requireEnv("CLOUDFLARE_ACCOUNT_ID");
  const baseUrl = requireEnv("REMOTE_MCP_PUBLIC_BASE_URL").replace(/\/+$/, "");
  const hostname = new URL(baseUrl).host;
  const appName = getTrimmedEnv(
    "REMOTE_MCP_ACCESS_APP_NAME",
    "iCloudPlugin Remote MCP",
  );
  const sessionDuration = getTrimmedEnv("ACCESS_SESSION_DURATION", "24h");
  const serviceTokenName = getTrimmedEnv(
    "ACCESS_SERVICE_TOKEN_NAME",
    "iCloudPlugin Remote MCP Service Token",
  );
  const allowedEmails = getTrimmedEnv("ACCESS_ALLOWED_EMAILS")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  const includeRules =
    allowedEmails.length > 0
      ? allowedEmails.map((email) => ({ email: { email } }))
      : [{ login_method: { id: "REPLACE_WITH_LOGIN_METHOD_ID" } }];

  const appPayload = {
    name: appName,
    domain: hostname,
    type: "self_hosted",
    app_launcher_visible: false,
    auto_redirect_to_identity: true,
    session_duration: sessionDuration,
  };

  const policyPayload = {
    name: `${appName} Allow`,
    decision: "allow",
    include: includeRules,
    session_duration: sessionDuration,
  };

  console.log(`# Cloudflare Access bootstrap for ${hostname}\n`);
  console.log(
    `# 1. Create the self-hosted Access application (recommended model for remote MCP according to Cloudflare docs)\n` +
      `curl https://api.cloudflare.com/client/v4/accounts/${accountId}/access/apps \\\n` +
      `  -H 'Authorization: Bearer $CLOUDFLARE_API_TOKEN' \\\n` +
      `  -H 'Content-Type: application/json' \\\n` +
      `  --data '${escapeSingleQuotes(JSON.stringify(appPayload))}'\n`,
  );
  console.log(
    "# 2. Create an allow policy for that Access app (replace <APP_ID> with the created application id)\n" +
      `curl https://api.cloudflare.com/client/v4/accounts/${accountId}/access/apps/<APP_ID>/policies \\\n` +
      `  -H 'Authorization: Bearer $CLOUDFLARE_API_TOKEN' \\\n` +
      `  -H 'Content-Type: application/json' \\\n` +
      `  --data '${escapeSingleQuotes(JSON.stringify(policyPayload))}'\n`,
  );
  console.log(
    "# 3. Optional: enable single-header service-token auth on the Access app for operator/bootstrap use\n" +
      "#    This follows Cloudflare's documented read_service_tokens_from_header = Authorization pattern.\n" +
      `curl https://api.cloudflare.com/client/v4/accounts/${accountId}/access/apps/<APP_ID> \\\n` +
      `  -X PUT \\\n` +
      `  -H 'Authorization: Bearer $CLOUDFLARE_API_TOKEN' \\\n` +
      `  -H 'Content-Type: application/json' \\\n` +
      `  --data '{\"name\":\"${escapeSingleQuotes(appName)}\",\"domain\":\"${hostname}\",\"type\":\"self_hosted\",\"read_service_tokens_from_header\":\"Authorization\"}'\n`,
  );
  console.log(
    "# 4. Optional: create a dedicated Access service token for machine-to-machine bootstrap or smoke checks\n" +
      `curl https://api.cloudflare.com/client/v4/accounts/${accountId}/access/service_tokens \\\n` +
      `  -H 'Authorization: Bearer $CLOUDFLARE_API_TOKEN' \\\n` +
      `  -H 'Content-Type: application/json' \\\n` +
      `  --data '${escapeSingleQuotes(JSON.stringify({ name: serviceTokenName, duration: "8760h" }))}'\n`,
  );
  console.log(
    "# 5. After authenticating once with the service token, later requests can send cf-access-token according to Cloudflare's docs.\n" +
      `#    Worker URL: ${baseUrl}/mcp\n` +
      `#    Health URL: ${baseUrl}/healthz\n`,
  );
}

main();
