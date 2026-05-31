## 2026-05-31 - Complete external ChatGPT / MCP access path with Cloudflare

- Source prompt: "we should put the mcp server in cloudflare" and later "do everything we need to do with the icloudplugin project to make a complete end to end product with all the capabilities we discussed".
- Interpreted requirement: move beyond the thin local-only MCP bridge and build
  a production-shaped external MCP access path for `iCloudPlugin` using a
  Cloudflare-hosted remote MCP server while keeping the on-prem index and
  classifier service as the source of truth.
- Product requirements:
  - search files
  - search once and hydrate the top note-plus-file bundles for external analysis
  - retrieve file metadata
  - retrieve source excerpts
  - retrieve generated note content
  - resolve canonical source links
  - retrieve or securely hand off original source files when appropriate
  - support a combined note-plus-file retrieval workflow for external AI access
- Architectural constraints:
  - do not move the canonical vault source of truth into iCloud Drive without
    a separate, explicit tradeoff decision
  - prefer a shared-vault canonical backend plus optional convenience export
  - keep origin auth and deployment shape real, not theoretical
- Tracking issue: [#48](https://github.com/NeonButrfly/iCloudPlugin/issues/48)
- First implementation slice:
  - plugin-token auth for plugin-facing origin routes
  - new note/source/download routes on the on-prem service
  - repo-local MCP bridge expanded to expose note/source/bundle tools
  - Cloudflare Worker scaffold in `cloudflare/remote-mcp`
  - Cloudflare account-side deployment still pending because account auth was
    not available in-session
- Follow-up implementation slice:
  - add `search_icloud_notes_and_files` so external ChatGPT can search once and
    immediately receive hydrated bundles for the top matches, including:
    - indexed file metadata and excerpt
    - generated note content
    - canonical source-link / download-handoff metadata
- Follow-up implementation slice:
  - move the combined retrieval path into the origin service as
    `GET /search/bundles` so bundle assembly logic is not duplicated across:
    - the repo-local MCP bridge
    - the Cloudflare Worker MCP facade
- Follow-up implementation slice:
  - harden the Cloudflare Worker for private real-world use with:
    - optional client-to-Worker bearer auth via `WORKER_API_TOKEN`
    - public non-secret health metadata at `/` and `/healthz`
    - explicit documentation that this private-token mode is the bootstrap path
      before a fuller OAuth front door such as Cloudflare Access
- Follow-up implementation slice:
  - add repo-local operator helpers so Cloudflare deployment stops depending on
    shell memory:
    - `cloudflare/remote-mcp/scripts/deploy-and-verify.mjs`
    - `cloudflare/remote-mcp/scripts/print-access-bootstrap.mjs`
  - keep the Worker itself stateless and align the production auth model with
    Cloudflare's recommended self-hosted Access application flow instead of
    growing custom auth logic inside the Worker
- Follow-up implementation slice:
  - add a first-class live status surface for external MCP callers through:
    - origin `GET /status/summary`
    - local MCP `get_icloud_system_status`
    - Cloudflare Worker `get_icloud_system_status`
  - status payload should expose:
    - service health
    - auth/session status
    - refresh progress
    - mirror sync status
    - classifier health/readiness
    - classification queue and state counts
    - provider counts
    - generated vault output counts
    - generated-note classifier-context gap counts for legacy notes that still
      lack `source_parser`, `heuristic_primary_hint`, or `hybrid_live_source`
- Follow-up implementation slice:
  - make the Cloudflare deploy helper push Worker secrets directly when auth is
    available, instead of requiring manual `wrangler secret put` steps first
  - support secret loading from shell env or a local `.dev.vars`-style file so
    the same local dev secret source can drive real deploys
- Follow-up implementation slice:
  - add a real remote-MCP smoke verifier that:
    - connects to the deployed `/mcp` route over Streamable HTTP
    - lists tools and confirms the expected external tool surface exists
    - calls one live probe tool, defaulting to `get_icloud_system_status`
  - keep this separate from `/healthz` so operators can verify actual MCP
    usability instead of only Worker reachability
- Follow-up implementation slice:
  - fold the remote-MCP smoke verifier into the deploy helper so a successful
    deploy can prove the actual `/mcp` surface in the same operator flow
  - support custom verify headers so the same verifier can work through
    Cloudflare Access or other front-door auth layers, not just the temporary
    Worker bearer gate
- Follow-up implementation slice:
  - replace the Worker's MCP route dependency on Cloudflare's broader `agents`
    package with a lighter in-repo stateless handler built directly on the MCP
    SDK Web Standard transport
  - use that slimmer handler to enable a real local end-to-end MCP test path in
    plain Node/Vitest while keeping the Cloudflare Worker shape intact
- Follow-up implementation slice:
  - add a deploy-shaped local Worker verifier for the pre-auth gap:
    - `cloudflare/remote-mcp/scripts/dev-and-verify.mjs`
  - it should:
    - start `wrangler dev` with temporary env-file wiring
    - wait for `/healthz`
    - verify `/mcp` with the real Streamable HTTP MCP smoke client
    - fail fast if the MCP probe hangs
    - clean up local Windows `workerd` processes when done
  - direct `GET /mcp` should return `405 Allow: POST, DELETE` so
    streamable-http clients can fall through cleanly instead of hanging on a
    standalone SSE path
