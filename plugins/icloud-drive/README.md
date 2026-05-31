# iCloud Drive MCP Plugin

This local plugin starts the thin `icloud_plugin_mcp` proxy and forwards MCP tool calls to the existing iCloud index service.

## Setup

1. Run `python -m pip install -e .` from the repo root so the `icloud-plugin-mcp` command is installed.
2. Make sure the iCloud index service is already running.
3. Set `ICLOUD_INDEX_SERVICE_URL` if the service is not on `http://127.0.0.1:8080`.
4. Set `ICLOUD_INDEX_API_TOKEN` if your local service expects bearer auth.

The plugin launcher in `.mcp.json` bootstraps the repo-local `src/` tree automatically, so it does not depend on the package already being importable just to find `icloud_plugin_mcp.server`.

## Run

```bash
python -m icloud_plugin_mcp.server
```

The plugin exposes:

- `search_icloud_files`
- `search_icloud_notes_and_files`
- `get_icloud_system_status`
- `get_icloud_file`
- `get_icloud_file_excerpt`
- `get_icloud_note`
- `get_icloud_source_reference`
- `get_icloud_file_bundle`
- `refresh_icloud_index`

The combined search tool now uses the backing service's `/search/bundles`
endpoint instead of stitching separate note/source lookups client-side.

The live-status tool uses the backing service's `/status/summary` endpoint so
external callers can inspect refresh progress, classifier readiness, queue
counts, provider counts, and vault output counts without shell access.
