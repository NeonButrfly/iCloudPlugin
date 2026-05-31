# iCloudPlugin Remote MCP on Cloudflare

This Worker is the Cloudflare-hosted MCP facade for `iCloudPlugin`.

It keeps the on-prem index/classifier service as the source of truth and exposes
remote MCP tools over Streamable HTTP at `/mcp`.

## What it exposes

- `search_icloud_files`
- `search_icloud_notes_and_files`
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

## Local development

```bash
npm install
npm run type-check
npm run dev
```

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
