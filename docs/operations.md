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

## Role-based deployment files

Use the role-specific Compose files when sync and classifier stay on different
hosts:

- `deploy/roles/cloudsync/docker-compose.yml`
  - use on the sync/index/API host such as `kayraspi2`
- `deploy/roles/classifier/docker-compose.yml`
  - use on the classifier/Ollama host such as `tichuml1`
- `deploy/roles/combined/docker-compose.yml`
  - use only when one host should run both sides together

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
- set `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors`
- make sure the host mirror mount is also visible inside the containers; by default compose binds `${ICLOUD_MIRROR_MOUNT_SOURCE:-/srv/cloud-vault}` to `/srv/cloud-vault`
- leave Apple credentials unset unless you still want the optional direct mode

In this mode:

- `/auth/status` reports `configured` when the mirror root is configured
- refresh jobs crawl the mirrored filesystem root and reuse the same resumable
  batch/frontier behavior
- content extraction still respects `ICLOUD_MAX_DOWNLOAD_BYTES`

## Cloud-vault mirror sync

The live storage host uses a host-level `rclone` timer to keep the mirror tree
current. The role now expects bidirectional sync rather than one-way pull-only
copies.

Canonical host-side mappings:

- `icloud:` <-> `/srv/cloud-vault/mirrors/icloud`
- `gdrive1:` <-> `/srv/cloud-vault/mirrors/google1`
- `gdrive2:` <-> `/srv/cloud-vault/mirrors/google2`

Classifier and indexing source-of-truth:

- point `ICLOUD_MIRROR_ROOT` at the aggregate root `/srv/cloud-vault/mirrors`
- keep provider-specific provenance in the first path segment:
  - `/icloud/...`
  - `/google1/...`
  - `/google2/...`
- do not funnel Google Drive content into iCloud just to create a single cloud
  provider source; use the local aggregate mirror as the single classifier
  source of truth instead

Recommended live assets:

- `deploy/roles/cloudsync/cloud-vault-sync.sh`
- `deploy/roles/cloudsync/cloud-vault-sync.service`
- `deploy/roles/cloudsync/cloud-vault-sync.timer`

Behavior:

- `rclone bisync` is used for each configured remote
- the first iCloud run seeds bisync state from the local mirror so the existing
  iCloud mirror is not discarded
- the first Google Drive runs seed bisync state from the remote Drive accounts
  so newly connected or empty local Google mirrors do not become authoritative
- remotes that are missing or unauthenticated are logged and skipped instead of
  failing the entire timer run
- Google Drive dangling shortcuts are skipped because they cannot be read as
  source objects during mirror initialization
- `RCLONE_TEST` is maintained as the access-health probe file for bisync

Current Google Drive expectation:

- `gdrive1` should map to `kaymayers9@gmail.com`
- `gdrive2` should map to `keifmayers@gmail.com`

If a Google Drive remote exists without a valid OAuth token, `rclone` will not
be able to access it. Complete the one-time `rclone config reconnect` or
`rclone config create` flow for that remote before expecting the timer to sync
it successfully.

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
  not replace the underlying host-level cloud sync direction
- the canonical vault root for that role is now `/srv/cloud-vault/document-vault`
- the old `/srv/cloud-vault/local-doc-classifier-vault` name is a compatibility
  symlink during the soak period
- default throughput is intentionally conservative:
  `CLASSIFICATION_SUBMISSION_CONCURRENCY=2`
- `CLASSIFICATION_MAX_ATTEMPTS` controls retry budget
- `CLASSIFICATION_RETRY_BACKOFF_SECONDS` controls when retriable failures can
  be claimed again; the current default is `0`
- Codex arbitration is opt-in only. Keep `CODEX_ARBITER_ENABLED=0` unless an
  operator intentionally enables the Codex final-arbiter path tracked in issue
  #20. With the default value, classifier submissions do not pass the Codex
  arbiter flag into the note-generation process.

### Reset state

As of 2026-05-24 AKDT, `document-vault` was intentionally reset before the full
all-drive note run. The automated `classification-worker` is paused, generated
vault content was cleared, classifier job/state rows were cleared, and trained
classifier artifacts such as `lightgbm-classifier.joblib`,
`taxonomy-router.joblib`, `corrections.jsonl`, and `examples.jsonl` were removed.

The source mirrors and `files` index were preserved. One manual smoke
classification was run from `google1`:

- `/srv/cloud-vault/mirrors/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx`

Generated Obsidian note and extracted-markdown filenames should use that
canonical source filename, not the classifier API's temporary staged upload name.
For canonical mirror submissions, issue #19 makes the note's `attachment` and
`source_link` metadata point back to the mirrored source file; the classifier
should not create a duplicate file under `90 Attachments`.

Medical or insurance appeal classifications should be written under
`01 Classified/medical/appeals` with a visible suffix of `medical - appeals`,
not as a vague top-level `appeal` category.

Do not resume bulk real-folder submissions until classifier readiness has been
rebuilt and `/readiness` reports `real_ingestion_allowed=true`.

Current classifier submission coverage follows the classifier API's accepted
extensions:

- documents: `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`,
  `.txt`, `.md`, `.markdown`, `.csv`, `.html`, `.htm`
- images: `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp`

Useful endpoints:

- `POST /refresh` queues a manual refresh
- `GET /refresh/status` reports the latest known job status and progress
- `GET /auth/status` reports whether the current Apple session is usable

## LightGBM retrain from live index

When the classifier model is missing after a reset, rebuild it from the live
iCloud index rather than from ad hoc runtime rows. The retrain helper now uses
a stratified 300-row sample that is split across provider-balanced docs,
sensitive-keyword files, low-confidence and ambiguous rows, and file-type
coverage before fitting LightGBM (#21).

Use:

```bash
python -m apps.classifier.retrain_hybrid_model
```

If the runtime row cache is empty, the helper falls back to the live index DB
configured through `INDEX_DATABASE_URL` or the `INDEX_POSTGRES_*` env vars.

## External taxonomy refresh and router rebuild

The classifier now keeps a local alias artifact derived from enabled public
taxonomy sources such as Open Images, Google Product Taxonomy, IAB Content
Taxonomy, DocLayNet, RVL-CDIP, CORD, and SROIE so both the runtime heuristics
and training paths can reuse the same mapped evidence phrases (#23).

Refresh the alias artifact from the configured public sources:

```bash
python -c "from apps.classifier.external_taxonomy import refresh_external_taxonomy_aliases; print(refresh_external_taxonomy_aliases())"
```

Then rebuild the taxonomy router so those aliases become part of candidate
selection:

```bash
python -m apps.classifier.taxonomy_router.train_taxonomy_router
```

If disagreement analysis shows generic alias noise or weak raw buckets that need
more reviewed examples, update the checked-in prune config and regenerate the
reviewed examples file from the current combined reviewed manifest:

```bash
python -m apps.classifier.reviewed_training
```

That command refreshes:

- `config/examples.jsonl`
- `config/reviewed-examples-report.json`

The report includes imported weak-bucket counts plus the current top noisy and
helpful alias hits derived from the reviewed manifest (#24).

## Taxonomy expansion and example mining

Issue [#25](https://github.com/NeonButrfly/iCloudPlugin/issues/25) expands the
raw label set using recurring live-vault directory and filename patterns, then
rebuilds a 500-row source-backed example corpus with explicit evidence fields.

For local desktop runs on Windows, classifier runtime defaults now resolve back
into the repo:

- `config/` for config artifacts
- `.runtime/classifier/` for runtime output
- `.runtime/input/api/` for local input
- `.runtime/vault/` for local vault mirrors

That keeps Codex retraining work inside the workspace instead of falling back
to container-style roots such as `/config` and `/output`.

Refresh the reviewed seed rows first:

```bash
python -m apps.classifier.reviewed_training
```

Then rebuild the live-index sanity-checked example corpus:

```bash
python -c "from apps.classifier.example_mining import mine_example_corpus; import json; print(json.dumps(mine_example_corpus(), ensure_ascii=True))"
```

The example corpus and report now include:

- `source_path`
- `summary`
- `teacher_evidence`
- `teacher_ranked_labels`
- `matched_terms`
- `source_extension`
- `source_mime_type`

Those fields are consumed by the taxonomy router and LightGBM runtime training
rows so both layers train on the same evidence-rich examples.

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
ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors
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
