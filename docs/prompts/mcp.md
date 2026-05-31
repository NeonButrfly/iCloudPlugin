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
