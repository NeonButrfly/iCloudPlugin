# iCloudPlugin Remote MCP on Cloudflare

This Worker is the Cloudflare-hosted MCP facade for `iCloudPlugin`.

It keeps the on-prem index/classifier service as the source of truth and exposes
remote MCP tools over Streamable HTTP at `/mcp`.

## What it exposes

- `search_icloud_files`
- `get_icloud_file`
- `get_icloud_file_excerpt`
- `get_icloud_note`
- `get_icloud_source_reference`
- `get_icloud_file_bundle`
- `refresh_icloud_index`

The source-reference tool includes a Worker download URL when the origin reports
that the original file can be handed off safely.

## Required origin configuration

The Worker expects the on-prem service to expose the plugin-facing API with a
bearer token:

- `ORIGIN_BASE_URL`
- `ORIGIN_API_TOKEN`

Recommended: keep the Worker itself behind Cloudflare Access or another OAuth
front door rather than deploying it as a public authless MCP endpoint.

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
npm run deploy
```

The resulting remote MCP endpoint lives at:

- `https://<worker>.<account>.workers.dev/mcp`

The download handoff route lives at:

- `https://<worker>.<account>.workers.dev/download/<file_id>`
