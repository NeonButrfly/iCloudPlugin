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
  - add a first-class product-readiness surface for external MCP callers
    through:
    - origin `GET /status/readiness`
    - local MCP `get_icloud_product_readiness`
    - Cloudflare Worker `get_icloud_product_readiness`
  - the readiness payload should expose:
    - the current live `status_summary`
    - repo-surface facts about MCP/deploy/helper coverage
    - explicit end-to-end criteria marked `met`, `blocked`, or `unknown`
- Follow-up implementation slice:
  - make the Cloudflare deploy helper push Worker secrets directly when auth is
    available, instead of requiring manual `wrangler secret put` steps first
  - support secret loading from shell env or a local `.dev.vars`-style file so
    the same local dev secret source can drive real deploys
- Follow-up implementation slice:
  - add a real remote-MCP smoke verifier that:
    - connects to the deployed `/mcp` route over Streamable HTTP
    - lists tools and confirms the expected external tool surface exists
    - calls one live probe tool, defaulting to `get_icloud_product_readiness`
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
- Follow-up implementation slice:
  - make the MCP descriptor surface more submission-ready by explicitly setting
    tool annotations and structured output contracts instead of leaving them
    implied
  - read tools should declare:
    - `readOnlyHint=true`
    - `openWorldHint=false`
    - `destructiveHint=false`
  - `refresh_icloud_index` should declare:
    - `readOnlyHint=false`
    - `openWorldHint=false`
    - `destructiveHint=false`
  - both the repo-local FastMCP bridge and the Cloudflare Worker tool surface
    should expose an `outputSchema` for every tool
- Follow-up implementation slice:
  - add explicit aggregate refresh control surfaces so operators can pause and
    resume a long-running index without losing the saved frontier
  - expose:
    - origin `POST /refresh/pause`
    - origin `POST /refresh/resume`
    - local MCP `pause_icloud_index`
    - local MCP `resume_icloud_index`
    - Cloudflare Worker `pause_icloud_index`
    - Cloudflare Worker `resume_icloud_index`
  - persist pause state outside the database so worker restarts continue to
    respect the operator pause until an explicit resume request arrives
- Follow-up implementation slice:
  - add a `chatgpt-app-submission.json` artifact for the remote MCP surface so
    the current ChatGPT Apps submission-facing view of the product is checked
    into the repo instead of being reconstructed from memory
  - keep it aligned with:
    - actual tool names
    - explicit annotations
    - review-facing positive and negative test cases
  - add a generator/verification path so that artifact can be re-derived from
    structured source data instead of drifting as a one-off hand edit

## 2026-07-01 - Make the checked-in iCloud Drive plugin installable through Codex

- Source prompt: "help me create a plugin to connect to my icloudplugin".
- Interpreted requirement: keep the existing `plugins/icloud-drive` MCP bridge
  as the source of truth, but add a first-class install path so Codex can add
  the plugin from the checked-in repo marketplace without manual local file
  edits.
- Product requirements:
  - validate the checked-in plugin metadata and marketplace entry
  - emit the exact `codex plugin marketplace add` and `codex plugin add`
    commands for the active repo checkout
  - document the install/reinstall flow where operators already look
- Architectural constraints:
  - do not fork the plugin into a second source of truth outside the repo
  - keep `plugins/icloud-drive` and `.agents/plugins/marketplace.json` as the
    authoritative packaging inputs
  - preserve the repo-local bootstrap fallback in `.mcp.json`
- Tracking issue: [#73](https://github.com/NeonButrfly/iCloudPlugin/issues/73)

## 2026-07-01 - Make ChatGPT setup use Secure MCP Tunnel first

- Source prompt: "make this easy for me" after verifying the hosted Worker was
  up but blocked by `worker-api-token` auth on `/mcp`.
- Interpreted requirement: make private ChatGPT connectivity for
  `iCloudPlugin` easy by preferring Secure MCP Tunnel over the current
  Cloudflare Worker token gate for first-time setup.
- Product requirements:
  - provide one repo-owned command for the local MCP bridge
  - provide one repo-owned helper that prints the Secure MCP Tunnel setup plan
  - point operators at the official OpenAI ChatGPT/tunnel docs instead of
    expecting them to infer the flow
- Architectural constraints:
  - reuse the checked-in `apps.mcp.server` / `icloud_plugin_mcp.server`
  - keep the private/local MCP path as the recommended easy option
  - do not claim the current `WORKER_API_TOKEN` gate is the preferred ChatGPT
    connector auth model
- Tracking issue: [#74](https://github.com/NeonButrfly/iCloudPlugin/issues/74)

## 2026-07-02 - Add full vault CRUD and reversible backups to the ChatGPT plugin

- Source prompt: "change icloud plugin so chatgpt has access to read/write/delete/create all files from all vaults (google1, google2, and iCloud) also make sure that the plugin can read/write/delete/create to/from obsidian document-vault and make sure chatgpt knows from the plug in that it can seperately work with the obsidian vault as part of this plugin", followed by refinements requiring `_`-directory hiding, `_CHANGES_BACKUP`, retroactive `_DUPLICATE_QUARANTINE` import, structured Obsidian note creation, direct accessible file links, automatic feedback sync, source-note sync, and first-class undo.
- Interpreted requirement: extend the origin service and ChatGPT-facing plugin/MCP surfaces so ChatGPT can perform full reversible CRUD across `google1`, `google2`, `icloud`, and `document_vault`, while hiding `_`-prefixed directories from normal discovery, routing all destructive changes through `_CHANGES_BACKUP`, and reusing the local categorizer's structured Obsidian note-writing and feedback conventions.
- Product requirements:
  - support path-based and file-id-based mirror operations
  - treat `document_vault` as a separate first-class namespace
  - keep normal read/list/search tools from exposing `_`-prefixed directories
  - allow internal backup/restore logic to write to and read from `_` areas as needed
  - make delete mean move into `_CHANGES_BACKUP` plus logged reversible change sets
  - expose first-class restore/undo
  - automatically feed relevant Obsidian note changes back through the existing feedback sync path
  - keep source files and related Obsidian notes in sync on delete/restore
  - merge `_DUPLICATE_QUARANTINE` and earlier `/home/kay` dedupe artifacts into the `_CHANGES_BACKUP` structure
- Architectural constraints:
  - operate on `tichuml1` against the mounted shared NFS paths, not by per-operation SSH hops to the Pi
  - keep `kayraspi2` as storage truth and `tichuml1` as runtime execution host
  - reuse the existing categorizer note contract instead of inventing a second Obsidian format
  - prefer vault-local attachment links for cross-platform file accessibility in structured `document_vault` notes
  - keep `_`-prefixed directories ignored by categorization
- Tracking issue: [#84](https://github.com/NeonButrfly/iCloudPlugin/issues/84)
