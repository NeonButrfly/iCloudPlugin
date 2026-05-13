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
- `get_icloud_file`
- `get_icloud_file_excerpt`
- `refresh_icloud_index`
