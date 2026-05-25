# iCloud Index Plugin

This repository contains a private cloud-vault platform for mirrored-drive
sync, indexing, classifier note generation, and its companion local MCP
plugin.

## Current state

The repository now includes:

- a FastAPI service with `/health`, `/auth/status`, `/refresh`, `/search`, and `/files/{file_id}`
- Docker Compose wiring for `postgres`, `migrate`, `service`, `worker`, and `classification-worker`
- metadata refresh jobs, stale-job recovery, extraction, and indexed file search
- a thin local MCP plugin that proxies search, file details, excerpts, and refresh calls to the service
- a parallel classifier submission lane that backfills indexed files and pushes mirrored source files to `local-doc-classifier`
- a role-based monorepo skeleton under `apps/`, `packages/`, and `deploy/roles`

The current implementation is read-heavy for indexing/search, with host-level
mirror sync now expected to support bidirectional `rclone bisync` on the
storage host.

## Readiness note

The live refresh path now supports two source modes in
`src/icloud_index_service/services/icloud_web_client.py`:

- `apple-web`
  - indexed search, file-detail retrieval, MCP wiring, upgrade hooks, and direct Drive traversal are implemented
  - refresh jobs require `ICLOUD_APPLE_ID` and `ICLOUD_APPLE_PASSWORD`
  - accounts protected by 2FA/2SA still need one trusted interactive `pyicloud` bootstrap so the persisted cookie directory can be reused by the service
- `filesystem-mirror`
  - refresh jobs crawl a live mirrored filesystem root instead of talking to Apple directly
  - configure `ICLOUD_SOURCE_MODE=filesystem-mirror`
  - configure `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors` on `kayraspi2`
  - make `/srv/cloud-vault` available inside the service and worker containers, or override `ICLOUD_MIRROR_MOUNT_SOURCE` if the host mount lives elsewhere

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
- the long-running `postgres`, `service`, and `worker` containers now use `restart: unless-stopped` so the stack comes back after host or Docker daemon restarts without a manual `docker compose up -d` (#5)
- the dedicated `classification-worker` container runs beside the refresh worker so classifier submission does not block indexing
- the worker applies extraction when payloads are available and records best-effort extraction failures without failing the whole refresh
- the plugin launcher in `plugins/icloud-drive/.mcp.json` starts the real MCP proxy, with a repo-local bootstrap fallback when the package import path is not already installed
- the source client reads `ICLOUD_SOURCE_MODE`, optional `ICLOUD_MIRROR_ROOT`, `ICLOUD_APPLE_ID`, `ICLOUD_APPLE_PASSWORD`, optional `ICLOUD_COOKIE_DIRECTORY`, and `ICLOUD_MAX_DOWNLOAD_BYTES`
- refresh runs are tracked in the database and resumed in the background from the
  last persisted traversal frontier instead of restarting from the top on every
  worker loop
- the worker automatically enqueues a background scan for new or changed files
  based on `BACKGROUND_REFRESH_INTERVAL_SECONDS`
- `GET /refresh/status` returns the latest known indexing state, including job
  progress for resumable scans
- extracted text is sanitized before persistence so embedded NUL bytes do not
  crash Postgres writes
- the container image now includes Tesseract so common still-image formats can
  be OCRed during indexing
- classifier submission reads mirrored files directly from the mounted
  filesystem tree and records durable per-file classification state so
  unchanged files are not re-submitted
- classifier submissions now pass canonical live-file path and hash metadata to
  the classifier so generated notes do not fall back to temporary upload
  staging paths
- the classification worker can run a bounded vault reconciliation pass against
  `CLASSIFIER_VAULT_ROOT` to repair stale note metadata after mirrored rename or
  move events
- the default classifier-facing vault root now points at
  `/srv/cloud-vault/document-vault`

## Indexing behavior

- refresh work is processed in small batches controlled by
  `ICLOUD_REFRESH_BATCH_FILE_LIMIT`
- each batch persists discovered files immediately and stores the remaining
  traversal frontier in the job payload
- a restarted or recovered worker resumes from the saved frontier and continues
  the same scan and sync run
- restart recovery does not consume retry budget; retries remain reserved for
  real crawl, auth, extraction, or unusable-state failures
- deletions are applied only after the full sync run completes
- `ICLOUD_EXCLUDED_DIRECTORY_NAMES` can skip large generated folders in addition
  to the built-in excludes for paths like `.git`, `node_modules`, `.venv`,
  `__pycache__`, `build`, and `dist`
- content extraction currently supports text-like files such as `.txt`, `.md`,
  `.csv`, `.json`, `.log`, `.html`, `.css`, `.yml`, `.yaml`, `.ics`, `.sql`,
  `.ts`, `.tsx`, and `.tsbuildinfo`
- document extraction currently supports `.pdf`, `.docx`, and `.xlsx`
- still-image OCR currently supports common formats such as `.jpg`, `.jpeg`,
  `.png`, `.gif`, `.webp`, and `.heic`
- video and audio formats remain metadata-only in this rollout

## Classification behavior

- the `classification-worker` backfills the already indexed corpus and keeps up
  with new or changed files while refresh jobs continue
- full-file uploads are sent to `CLASSIFIER_API_URL` using
  `POST /classify/upload`
- the default submission lane is low-concurrency by design:
  `CLASSIFICATION_SUBMISSION_CONCURRENCY=2`
- high-value file types are prioritized first:
  documents before images
- successful classifier responses are persisted into durable
  `classification_states` records, including note path, summary, and label
- files are submitted from the mirrored filesystem source, not re-downloaded
  from Apple during classification
- the canonical classifier-facing mirror root can be the aggregate
  `/srv/cloud-vault/mirrors`, preserving upstream-specific subfolders such as
  `/icloud`, `/google1`, and `/google2` under one local source of truth
- note reconciliation repairs note metadata only; it does not replace the
  separate host-level cloud sync job
- the new classifier role code lives in `apps/classifier`
- new note filenames should be human-readable by default, with hashes retained
  in metadata instead of dominating the visible file name
- current classifier submission coverage follows the classifier API’s supported
  file types:
  `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.txt`, `.md`,
  `.markdown`, `.csv`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.tif`,
  `.tiff`, `.bmp`, and `.webp`

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

## Role layout

- `apps/cloudsync`: sync and background crawl entrypoints
- `apps/classifier`: classifier API, note writer, and taxonomy helpers
- `apps/api`: operator API entrypoints
- `apps/mcp`: MCP bridge entrypoints
- `packages/*`: shared contracts, vault helpers, storage helpers, and runtime
  building blocks

## Role deployment files

The monorepo now ships separate deployable role stacks under `deploy/roles`:

- `deploy/roles/cloudsync/docker-compose.yml`
  - sync/indexing/API side for the storage host
- `deploy/roles/classifier/docker-compose.yml`
  - classifier/Ollama side for the classifier host
- `deploy/roles/combined/docker-compose.yml`
  - single-host combined deployment when needed
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
