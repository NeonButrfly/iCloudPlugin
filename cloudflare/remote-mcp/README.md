# iCloudPlugin Remote MCP on Cloudflare

This Worker is the Cloudflare-hosted MCP facade for `iCloudPlugin`.

It keeps the on-prem index/classifier service as the source of truth and exposes
remote MCP tools over Streamable HTTP at `/mcp`.

## What it exposes

- `search_icloud_files`
- `search_icloud_notes_and_files`
- `get_icloud_system_status`
- `get_icloud_file`
- `get_icloud_file_excerpt`
- `get_icloud_note`
- `get_icloud_source_reference`
- `get_icloud_file_bundle`
- `refresh_icloud_index`

The source-reference tool includes a Worker download URL when the origin reports
that the original file can be handed off safely.

All Worker tools now also declare explicit MCP tool annotations:

- read tools set:
  - `readOnlyHint=true`
  - `openWorldHint=false`
  - `destructiveHint=false`
- `refresh_icloud_index` sets:
  - `readOnlyHint=false`
  - `openWorldHint=false`
  - `destructiveHint=false`

The Worker tool descriptors now also include an explicit `outputSchema` for
every tool, which makes ChatGPT/App-review-side tool handling less guessy even
before the final hosted deployment proof is complete.

The combined search tool is meant to reduce round trips for external ChatGPT
workflows by searching once, then expanding the strongest matches into bundled:

- indexed file metadata and excerpt
- generated note content
- canonical source-path and download-handoff metadata

That bundled response now comes from the origin service's `/search/bundles`
endpoint, which keeps the bundle assembly logic in one place instead of
duplicating it in each client.

The live-status tool now comes from the origin service's `/status/summary`
endpoint, so external MCP callers can fetch one consolidated cloud-vault
status snapshot without SSH or several stitched probes.

That status snapshot now also includes generated-note classifier-context gap
counts, so external operators can see how many legacy notes still lack
`source_parser`, `heuristic_primary_hint`, or `hybrid_live_source` and whether
those gaps still line up with completed, queued, or missing backend state rows.

## Required origin configuration

The Worker expects the on-prem service to expose the plugin-facing API with a
bearer token:

- `ORIGIN_BASE_URL`
- `ORIGIN_API_TOKEN`

The Worker can also enforce its own bearer token for client-to-Worker access:

- `WORKER_API_TOKEN`

If `WORKER_API_TOKEN` is set, clients must send:

```http
Authorization: Bearer <worker token>
```

on both:

- `/mcp`
- `/download/<file_id>`

Public status endpoints:

- `/`
- `/healthz`

These return non-secret route and auth-mode metadata that help with deployment
verification.

Recommended long-term deployment shape:

- use `WORKER_API_TOKEN` for private bootstrap / operator testing
- move to Cloudflare Access OAuth or another OAuth front door before calling
  the external MCP path production-complete

Cloudflare's current guidance for remote MCP is:

- use a stateless `createMcpHandler()` Worker when tools do not need per-session
  state
- protect the deployed Worker with a self-hosted Cloudflare Access application
  when you want Cloudflare to own the OAuth flow
- optionally enable single-header service-token auth for operator/bootstrap use
  on that Access application

This repo follows that shape: the Worker stays stateless, and Access is the
recommended production auth front door instead of pushing more auth logic into
the Worker itself.

Implementation note:

- the Worker now uses a small in-repo stateless handler built directly on
  `@modelcontextprotocol/sdk`'s Web Standard Streamable HTTP transport
- it no longer depends on Cloudflare's broader `agents` package at runtime
- that keeps the Worker aligned with the stateless MCP guidance while making
  local end-to-end verification possible in plain Node/Vitest

## Local development

```bash
npm install
npm test
npm run type-check
npm run dev
```

The local test suite now includes an end-to-end MCP proof:

- a real MCP client connects to the Worker route
- `tools/list` succeeds
- tool annotations and `outputSchema` are present on the exposed descriptors
- `get_icloud_system_status` succeeds
- bundled search responses rewrite `worker_download_url` correctly

Local secret/example file:

- copy `.dev.vars.example` to `.dev.vars` for local `wrangler dev` work

Run a deploy-shaped local smoke before Cloudflare account auth is available:

```bash
npm run dev:verify
```

That helper:

- starts `wrangler dev` with a temporary env file built from shell env and
  optional `--secrets-file`
- waits for `/healthz`
- verifies `/mcp` with a real Streamable HTTP MCP client
- cleans up the local `workerd` process tree on Windows after the check

You can trim or tune it with:

- `--skip-health-check`
- `--skip-mcp-check`
- `--startup-timeout-ms <n>`
- `--verify-timeout-ms <n>`

## Deployment helpers

Plan the deploy and derived URLs without deploying:

```bash
npm run deploy:plan
```

Plan a deploy using secret values from a local `.env`-style file such as
`.dev.vars` without pushing anything yet:

```bash
node scripts/deploy-and-verify.mjs --plan --sync-secrets --secrets-file .dev.vars --json
```

Deploy with Wrangler and verify `/healthz` plus the live `/mcp` tool surface
afterward:

```bash
npm run deploy:verify
```

`deploy:verify` now proves, in one flow:

- the Worker deployed
- `/healthz` is healthy
- `/mcp` accepts a real Streamable HTTP MCP client
- the expected tool surface is present
- `get_icloud_system_status` succeeds

Trim that flow only when you mean to:

- `--skip-health-check`
- `--skip-mcp-check`
- repeated `--verify-header 'Name: Value'` for the MCP verification step

Verify the deployed `/mcp` route like a real MCP client by listing tools and
calling one probe tool:

```bash
npm run mcp:verify -- --base-url https://<worker>.<account>.workers.dev --json
```

If the Worker uses `WORKER_API_TOKEN`, either set it in the shell first or pass
it directly:

```bash
node scripts/verify-mcp-tools.mjs \
  --base-url https://<worker>.<account>.workers.dev \
  --token "$WORKER_API_TOKEN" \
  --json
```

By default the verifier:

- fetches `/healthz` first when a public base URL is available
- connects to `/mcp` over Streamable HTTP
- lists tools and confirms the expected tool surface exists
- calls `get_icloud_system_status` as the probe tool

It also supports richer auth than the Worker bootstrap token alone:

- `WORKER_API_TOKEN` or `--token` for the current Worker bearer gate
- repeated `--header 'Name: Value'` flags for custom front-door headers
- `REMOTE_MCP_VERIFY_HEADERS_JSON` for a shell-driven header bundle
- Cloudflare Access env fallbacks:
  - `CF_ACCESS_CLIENT_ID`
  - `CF_ACCESS_CLIENT_SECRET`
  - `CF_ACCESS_TOKEN`

You can override the probe tool and arguments when you want a deeper smoke run:

```bash
node scripts/verify-mcp-tools.mjs \
  --mcp-url https://<worker>.<account>.workers.dev/mcp \
  --probe-tool search_icloud_files \
  --probe-args '{"query":"appeal","limit":1}' \
  --json
```

Example using Cloudflare Access service-token headers:

```bash
node scripts/verify-mcp-tools.mjs \
  --base-url https://<worker>.<account>.workers.dev \
  --header "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  --header "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  --json
```

This helper expects:

- `ORIGIN_BASE_URL` and `ORIGIN_API_TOKEN`, either:
  - already present in the current shell environment
  - or loaded from `--secrets-file <path>` when `--sync-secrets` is used
- optional `WORKER_API_TOKEN`
- optional `REMOTE_MCP_PUBLIC_BASE_URL`
- either `CLOUDFLARE_API_TOKEN` or an existing Wrangler login

If you want the helper to push Worker secrets before deploy, add:

```bash
node scripts/deploy-and-verify.mjs --sync-secrets --secrets-file .dev.vars
```

That path:

- reads `ORIGIN_BASE_URL`
- reads `ORIGIN_API_TOKEN`
- reads optional `WORKER_API_TOKEN`
- pushes them with `wrangler secret bulk`
- then runs the deploy, `/healthz` verification, and remote MCP smoke flow

Print ready-to-run Cloudflare Access bootstrap commands for the deployed
Worker:

```bash
npm run access:plan
```

That helper emits:

- a self-hosted Access application create call
- an application policy create call
- an optional `read_service_tokens_from_header: "Authorization"` update
- an optional Access service-token create call

## Deployment

```bash
npm install
npx wrangler secret put ORIGIN_BASE_URL
npx wrangler secret put ORIGIN_API_TOKEN
npx wrangler secret put WORKER_API_TOKEN
npm run deploy
```

The resulting remote MCP endpoint lives at:

- `https://<worker>.<account>.workers.dev/mcp`

The download handoff route lives at:

- `https://<worker>.<account>.workers.dev/download/<file_id>`

The public health endpoint lives at:

- `https://<worker>.<account>.workers.dev/healthz`

Recommended production front door:

- keep `WORKER_API_TOKEN` for bootstrap/private smoke use if helpful
- place the public Worker behind Cloudflare Access as a self-hosted
  application
- use the emitted `access:plan` commands as the operator bootstrap for that
  Access layer
