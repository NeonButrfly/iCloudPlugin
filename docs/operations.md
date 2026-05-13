# Operations

## Deployment root

Use `/opt/iCloudPlugin` as the canonical Linux deployment path for the project
checkout, runtime session files, and operator scripts.

Expected layout:

- repo root: `/opt/iCloudPlugin`
- cookie/session directory: `/opt/iCloudPlugin/.runtime/pyicloud`
- scripts: `/opt/iCloudPlugin/scripts`

## Start the stack

```bash
cd /opt/iCloudPlugin
docker compose up --build
```

## Bootstrap Apple session

1. Open the auth bootstrap URL exposed by the service.
2. Complete the Apple web sign-in flow from a normal browser on another machine if the Linux host is headless.
3. Confirm `/auth/status` reports a usable session before relying on fresh refresh jobs.

Current flow:
- the repo now uses `pyicloud` for direct iCloud Drive access
- set `ICLOUD_APPLE_ID` and `ICLOUD_APPLE_PASSWORD`
- keep the cookie directory persisted so trusted Apple sessions survive restarts
- if Apple requires 2FA/2SA, complete one interactive trusted `pyicloud` login before expecting unattended refresh jobs to work

## Background indexing

- the worker keeps refresh work in the background and scans for new or changed
  files on a timer
- `BACKGROUND_REFRESH_INTERVAL_SECONDS` controls how often the worker should
  queue a new background scan when no newer completed scan exists
- `ICLOUD_REFRESH_BATCH_FILE_LIMIT` controls how many file entries are processed
  per resumable batch
- batch progress is stored in the `jobs` payload, so the worker can immediately
  resume where it left off after a restart
- file presence is tracked per sync run; deletions are applied only when the
  whole run finishes

Useful endpoints:

- `POST /refresh` queues a manual refresh
- `GET /refresh/status` reports the latest known job status and progress
- `GET /auth/status` reports whether the current Apple session is usable

## Local plugin

1. Run `python -m pip install -e .` from the repo root.
2. Keep the service reachable at `ICLOUD_INDEX_SERVICE_URL`, or leave it on the default `http://127.0.0.1:8080`.
3. Use the repo-local plugin in `plugins/icloud-drive`.

## Degraded mode

- Search and file APIs return controlled `503` responses when the database is unavailable.
- Auth-needed responses should preserve whether cached results exist so callers can decide whether to surface stale-but-useful data.

## Reindex from scratch

If the local index needs to be destroyed and rebuilt, use one of the provided
helpers:

```bash
cd /opt/iCloudPlugin
scripts/reindex-icloud-index.sh
```

```powershell
Set-Location /opt/iCloudPlugin
./scripts/reindex-icloud-index.ps1
```

The reindex helpers:

- bring up `postgres`, `service`, and `worker` if needed
- truncate `extracted_contents`, `files`, `jobs`, and `sync_runs`
- queue a fresh refresh run
- print the current `/refresh/status` payload

## Suggested environment values

For the Pi deployment, start with:

```dotenv
ICLOUD_COOKIE_DIRECTORY=.runtime/pyicloud
ICLOUD_REFRESH_BATCH_FILE_LIMIT=100
BACKGROUND_REFRESH_INTERVAL_SECONDS=1800
WORKER_POLL_INTERVAL_SECONDS=5
```

## Upgrade hooks

- AI categorization stays suggestion-only in this rollout: prompts should yield category, confidence, and reasoning, not move files.
- Markdown collections should aggregate summaries with clear provenance back to indexed source files.
