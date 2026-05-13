# iCloud Index Plugin

This repository contains a private iCloud Drive indexing stack and its companion local MCP plugin.

## Current state

The repository now includes:

- a FastAPI service with `/health`, `/auth/status`, `/refresh`, `/search`, and `/files/{file_id}`
- Docker Compose wiring for `postgres`, `migrate`, `service`, and `worker`
- metadata refresh jobs, stale-job recovery, extraction, and indexed file search
- a thin local MCP plugin that proxies search, file details, excerpts, and refresh calls to the service
- planning hooks for future AI categorization and markdown collection generation

The current implementation is read-only and iCloud-only.

## Readiness note

The live refresh path now uses a real `pyicloud`-backed iCloud Drive client in
`src/icloud_index_service/services/icloud_web_client.py`, but it still depends on
valid Apple credentials plus a trusted Apple session:

- indexed search, file-detail retrieval, MCP wiring, upgrade hooks, and direct Drive traversal are implemented
- refresh jobs require `ICLOUD_APPLE_ID` and `ICLOUD_APPLE_PASSWORD`
- accounts protected by 2FA/2SA still need one trusted interactive `pyicloud` bootstrap so the persisted cookie directory can be reused by the service

## Recommended deployment root

For the headless Linux deployment, keep the project checkout and runtime files
under `/opt/iCloudPlugin`.

- repo root: `/opt/iCloudPlugin`
- Apple cookie/session directory: `/opt/iCloudPlugin/.runtime/pyicloud`
- helper scripts: `/opt/iCloudPlugin/scripts`

## Runtime notes

- `docker compose up --build` works without creating `.env`
- copy `.env.example` to `.env` only if you want to override the default ports or credentials
- use `POSTGRES_PUBLISHED_PORT` to change the host-facing database port without changing the service's internal Postgres connection on `5432`
- the service container validates DB connectivity with `SELECT 1` before serving HTTP
- the worker applies extraction when payloads are available and records best-effort extraction failures without failing the whole refresh
- the plugin launcher in `plugins/icloud-drive/.mcp.json` starts the real MCP proxy, with a repo-local bootstrap fallback when the package import path is not already installed
- the direct iCloud client reads `ICLOUD_APPLE_ID`, `ICLOUD_APPLE_PASSWORD`, optional `ICLOUD_COOKIE_DIRECTORY`, and `ICLOUD_MAX_DOWNLOAD_BYTES`
- refresh runs are tracked in the database and resumed in the background from the
  last persisted traversal frontier instead of restarting from the top on every
  worker loop
- the worker automatically enqueues a background scan for new or changed files
  based on `BACKGROUND_REFRESH_INTERVAL_SECONDS`
- `GET /refresh/status` returns the latest known indexing state, including job
  progress for resumable scans

## Indexing behavior

- refresh work is processed in small batches controlled by
  `ICLOUD_REFRESH_BATCH_FILE_LIMIT`
- each batch persists discovered files immediately and stores the remaining
  traversal frontier in the job payload
- a restarted worker resumes from the saved frontier and continues the same scan
- deletions are applied only after the full sync run completes
- `ICLOUD_EXCLUDED_DIRECTORY_NAMES` can skip large generated folders in addition
  to the built-in excludes for paths like `.git`, `node_modules`, `.venv`,
  `__pycache__`, `build`, and `dist`

## Reindex reset

Use the provided reindex helpers when you need to destroy and rebuild the local
index from scratch:

```bash
scripts/reindex-icloud-index.sh
```

```powershell
./scripts/reindex-icloud-index.ps1
```

Both scripts:

- expect the Linux deployment root to be `/opt/iCloudPlugin` by default
- start the Compose services if needed
- truncate the index tables and sync history
- queue a fresh refresh run
- print the current `/refresh/status` response

## Local plugin

- plugin path: `plugins/icloud-drive`
- MCP tool surface:
  - `search_icloud_files`
  - `get_icloud_file`
  - `get_icloud_file_excerpt`
  - `refresh_icloud_index`
- install command:

```bash
python -m pip install -e .
```

## Validation

Focused service and plugin checks:

```bash
python -m pytest tests/test_health_api.py tests/test_search_api.py tests/test_plugin_client.py -v
```

Full regression suite:

```bash
python -m pytest tests -v
docker compose config
```

For operations guidance, see [docs/operations.md](/C:/Code/iCloudPlugin/docs/operations.md).
