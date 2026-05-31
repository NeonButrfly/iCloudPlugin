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

## Local development

```bash
npm install
npm test
npm run type-check
npm run dev
```

Local secret/example file:

- copy `.dev.vars.example` to `.dev.vars` for local `wrangler dev` work

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

Deploy with Wrangler and verify `/healthz` afterward:

```bash
npm run deploy:verify
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
- then runs the deploy and `/healthz` verification flow

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
