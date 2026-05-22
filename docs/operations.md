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

After the first successful start, the long-running `postgres`, `service`,
`worker`, and `classification-worker` containers are configured with
`restart: unless-stopped`, so normal host or Docker daemon restarts should
bring the API back automatically (#5).

## Bootstrap Apple session

1. Open the auth bootstrap URL exposed by the service.
2. Complete the Apple web sign-in flow from a normal browser on another machine if the Linux host is headless.
3. Confirm `/auth/status` reports a usable session before relying on fresh refresh jobs.

Current flow:
- the repo now uses `pyicloud` for direct iCloud Drive access
- set `ICLOUD_APPLE_ID` and `ICLOUD_APPLE_PASSWORD`
- keep the cookie directory persisted so trusted Apple sessions survive restarts
- if Apple requires 2FA/2SA, complete one interactive trusted `pyicloud` login before expecting unattended refresh jobs to work

## Filesystem mirror mode

If a maintained live mirror already exists, the service can index that tree
directly instead of traversing Apple web APIs.

For the `kayraspi2` deployment:

- set `ICLOUD_SOURCE_MODE=filesystem-mirror`
- set `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors/icloud`
- make sure the host mirror mount is also visible inside the containers; by default compose binds `${ICLOUD_MIRROR_MOUNT_SOURCE:-/srv/cloud-vault}` to `/srv/cloud-vault`
- leave Apple credentials unset unless you still want the optional direct mode

In this mode:

- `/auth/status` reports `configured` when the mirror root is configured
- refresh jobs crawl the mirrored filesystem root and reuse the same resumable
  batch/frontier behavior
- content extraction still respects `ICLOUD_MAX_DOWNLOAD_BYTES`

## Background indexing

- the worker keeps refresh work in the background and scans for new or changed
  files on a timer
- `BACKGROUND_REFRESH_INTERVAL_SECONDS` controls how often the worker should
  queue a new background scan when no newer completed scan exists
- `ICLOUD_REFRESH_BATCH_FILE_LIMIT` controls how many file entries are processed
  per resumable batch
- `ICLOUD_OCR_LANGS` controls the Tesseract language set used for still-image OCR
- batch progress is stored in the `jobs` payload, so the worker can immediately
  resume where it left off after a restart
- restart recovery keeps the same job frontier and sync run instead of opening
  a fresh scan
- restart recovery does not spend retry budget; retries are still reserved for
  real crawl, auth, extraction, or unusable-state failures
- file presence is tracked per sync run; deletions are applied only when the
  whole run finishes
- extracted text is sanitized before persistence so embedded NUL bytes do not
  crash Postgres writes

## Background classification

- `classification-worker` runs in parallel with the refresh worker
- it backfills the already indexed mirrored corpus and keeps up with new or
  changed files while indexing continues
- it submits full files to `CLASSIFIER_API_URL` using `CLASSIFIER_API_TOKEN`
- it persists per-file classification state so unchanged files are not
  resubmitted
- it reads files from the mirrored filesystem source instead of re-downloading
  them from Apple during submission
- it passes canonical live-file path and hash metadata through to the
  classifier so notes can refer back to the mirrored drive instead of temporary
  upload staging paths
- it can run a bounded vault reconciliation pass against `CLASSIFIER_VAULT_ROOT`
  after submission polls; this first pass repairs note metadata only and does
  not change mirror sync direction
- the default vault root for that role is now `/srv/cloud-vault/document-vault`
- default throughput is intentionally conservative:
  `CLASSIFICATION_SUBMISSION_CONCURRENCY=2`
- `CLASSIFICATION_MAX_ATTEMPTS` controls retry budget
- `CLASSIFICATION_RETRY_BACKOFF_SECONDS` controls when retriable failures can
  be claimed again; the current default is `0`

Current classifier submission coverage follows the classifier API's accepted
extensions:

- documents: `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`,
  `.txt`, `.md`, `.markdown`, `.csv`, `.html`, `.htm`
- images: `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp`

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

- bring up `postgres`, `service`, `worker`, and `classification-worker` if needed
- truncate `extracted_contents`, `files`, `jobs`, and `sync_runs`
- queue a fresh refresh run
- print the current `/refresh/status` payload

## Suggested environment values

For the Pi deployment, start with:

```dotenv
CLASSIFICATION_SUBMISSION_ENABLED=true
CLASSIFIER_API_URL=http://192.168.50.196:4319
CLASSIFIER_API_TOKEN=
CLASSIFIER_VAULT_ROOT=/srv/cloud-vault/document-vault
CLASSIFIER_VAULT_RECONCILIATION_ENABLED=true
CLASSIFIER_VAULT_RECONCILIATION_LIMIT=10
CLASSIFICATION_SUBMISSION_CONCURRENCY=2
CLASSIFICATION_SUBMISSION_POLL_INTERVAL_SECONDS=5
CLASSIFICATION_MAX_ATTEMPTS=3
CLASSIFICATION_RETRY_BACKOFF_SECONDS=0
ICLOUD_SOURCE_MODE=filesystem-mirror
ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors/icloud
ICLOUD_MIRROR_MOUNT_SOURCE=/srv/cloud-vault
ICLOUD_COOKIE_DIRECTORY=.runtime/pyicloud
ICLOUD_OCR_LANGS=eng
ICLOUD_REFRESH_BATCH_FILE_LIMIT=100
BACKGROUND_REFRESH_INTERVAL_SECONDS=1800
WORKER_POLL_INTERVAL_SECONDS=5
```

## Current extraction coverage

- text-like formats: `.txt`, `.md`, `.csv`, `.json`, `.log`, `.html`, `.css`,
  `.yml`, `.yaml`, `.ics`, `.sql`, `.ts`, `.tsx`, `.tsbuildinfo`
- documents: `.pdf`, `.docx`, `.xlsx`
- OCR images: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.heic`
- media such as `.mov`, `.mp4`, `.m4v`, `.m4a`, `.qt`, and `.avi` remain
  metadata-only in this rollout

## Upgrade hooks

- ChatGPT note-first retrieval can now build on persisted classifier note
  paths, summaries, labels, and response payloads stored in the index
  database.
- Markdown collections should aggregate summaries with clear provenance back to
  indexed source files and classifier-generated notes.
