# iCloud Drive MCP Plugin

This local plugin starts the thin `icloud_plugin_mcp` proxy and forwards MCP tool calls to the existing iCloud index service.

## Setup

1. Run `python -m pip install -e .` from the repo root so the `icloud-plugin-mcp` command is installed.
2. Make sure the iCloud index service is already running.
3. Set `ICLOUD_INDEX_SERVICE_URL` if the service is not on `http://127.0.0.1:8080`.
4. Set `ICLOUD_INDEX_API_TOKEN` if your local service expects bearer auth.

## Install In Codex

Use the checked-in repo marketplace instead of hand-editing local plugin files:

```bash
python scripts/install_codex_plugin.py
```

That helper validates the checked-in plugin and prints the exact marketplace and
install commands for this repo checkout.

If you want the same plan in machine-readable form:

```bash
python scripts/install_codex_plugin.py --json
```

Then run the emitted `codex plugin marketplace add ...` and
`codex plugin add ...` commands from a Codex-capable terminal or the Codex app.
After install or reinstall, start a new Codex thread so the updated plugin
tools are loaded.

The plugin launcher in `.mcp.json` bootstraps the repo-local `src/` tree automatically, so it does not depend on the package already being importable just to find `icloud_plugin_mcp.server`.

## Run

```bash
python -m icloud_plugin_mcp.server
```

The plugin exposes:

- `search_icloud_files`
- `search_icloud_notes_and_files`
- `get_icloud_system_status`
- `get_icloud_product_readiness`
- `get_icloud_file`
- `get_icloud_file_excerpt`
- `get_icloud_note`
- `get_icloud_source_reference`
- `get_icloud_file_bundle`
- `refresh_icloud_index`
- `pause_icloud_index`
- `resume_icloud_index`

Those MCP tools now also declare explicit tool annotations:

- read tools use:
  - `readOnlyHint=true`
  - `openWorldHint=false`
  - `destructiveHint=false`
- `refresh_icloud_index` uses:
  - `readOnlyHint=false`
  - `openWorldHint=false`
  - `destructiveHint=false`

The local bridge now also advertises structured output for every tool, so the
descriptor surface includes `outputSchema` instead of leaving models to infer
object-shaped results from the implementation alone.

The combined search tool now uses the backing service's `/search/bundles`
endpoint instead of stitching separate note/source lookups client-side.

The live-status tool uses the backing service's `/status/summary` endpoint so
external callers can inspect refresh progress, classifier readiness, queue
counts, provider counts, vault output counts, and generated-note
classifier-context gap counts without shell access.

The product-readiness tool uses the backing service's `/status/readiness`
endpoint so callers can inspect one consolidated end-to-end readiness report
through the same MCP bridge.
