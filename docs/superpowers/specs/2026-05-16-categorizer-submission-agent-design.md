# Categorizer Submission Agent Design

Date: 2026-05-16
Issue: #7
Milestone: `v1 - Private iCloud Index Service`

## Goal

Add a parallel categorizer submission agent inside `iCloudPlugin` that:

- backfills the already indexed corpus
- keeps submitting new or changed files while metadata ingestion continues
- pushes full files to the classifier API at `192.168.50.196:4319`
- records successful classification state so unchanged files are not re-submitted
- preserves the current indexing/search service as the authoritative source of file state

This design intentionally keeps `local-doc-classifier` authoritative for note
generation and vault writes, while `iCloudPlugin` becomes authoritative for file
discovery, submission state, and retrieval linkage.

## Chosen Approach

Recommended and approved behavior:

- `iCloudPlugin` owns durable classification submission jobs
- `iCloudPlugin` pushes full-file uploads to the classifier API
- `local-doc-classifier` does not pull from `iCloudPlugin`
- the classifier writes notes and attachments into the vault on
  `192.168.50.86` over NFS
- submission runs in parallel to metadata ingestion with low concurrency
- backfill starts with the entire already indexed corpus
- high-value files are prioritized first

Rejected alternatives:

- metadata-first classification shortcut for v1
  - rejected because the classifier already works on real files and the user
    prefers full-file analysis for better notes
- classifier pull model
  - rejected because the user wants `iCloudPlugin` to own submission and the
    classifier API already exposes a push-style upload contract
- vault existence as the blocking success criterion
  - rejected for v1 because API success is the cleaner primary contract and
    cross-host vault verification can be a later reconciler

## System Roles

### `iCloudPlugin`

Owns:

- file discovery and indexing
- mirrored filesystem source selection
- file version or content-hash-based change detection
- submission queue and retry state
- prioritization policy
- classifier API client behavior
- cached linkage to classifier outputs

### `local-doc-classifier`

Owns:

- full-file classification
- category, summary, confidence, and reasoning
- manifest creation
- Obsidian note generation
- vault writes and attachment handling

### Obsidian Vault

Lives on `192.168.50.86` and remains the primary note knowledge layer that
ChatGPT retrieval should prefer later.

## Data Model

Add new tables or their equivalent SQLAlchemy models plus migration support.

### `classification_jobs`

Purpose:

- durable submission queue for classifier work

Suggested fields:

- `id`
- `file_id` foreign key to `files.id`
- `status` (`queued`, `running`, `completed`, `failed`)
- `priority_bucket` (`document`, `text-backed`, `image`, `other`, `skipped`)
- `attempt_count`
- `max_attempts`
- `worker_id`
- `claimed_at`
- `heartbeat_at`
- `classifier_response_json`
- `error_message`
- `created_at`
- `updated_at`

Rules:

- at most one active classification job per file
- completed rows remain as audit history

### `classification_states`

Purpose:

- authoritative per-file classification status used to decide whether a file
  needs backfill or resubmission

Suggested fields:

- `file_id` unique foreign key
- `source_fingerprint`
- `source_size_bytes`
- `source_modified_at`
- `submission_status`
- `last_submitted_at`
- `last_completed_at`
- `classifier_note_path`
- `classifier_manifest_record`
- `primary_label`
- `summary`
- `confidence`
- `reasoning`
- `response_payload_json`
- `last_error`

Rules:

- one row per indexed file that has ever been considered for classification
- a file only needs resubmission when its current indexed fingerprint differs
  from the successful classified fingerprint or it has never succeeded

## Fingerprint Contract

The submission agent needs a stable notion of “already classified successfully.”

Use a source fingerprint derived from indexed file state:

- prefer extracted-content hash when available and the file is text-backed
- otherwise use a file-state fingerprint derived from:
  - path
  - size_bytes
  - modified timestamp if available

This keeps v1 practical even before a full binary hash is added for every file.

## Submission Priority

Backfill order:

1. PDFs, `.docx`, `.xlsx`, and text-like documents
2. files that already have extracted text rows
3. images with OCR potential
4. everything else
5. unsupported media can be left last or skipped by policy

Implementation rule:

- priority must be deterministic so backfill order is stable
- once a file is queued, ingestion should not create duplicate active jobs for it

## Submission Flow

### Backfill bootstrap

When the submission agent is first enabled:

1. scan indexed files in `files`
2. compare each file to `classification_states`
3. enqueue jobs for files with no successful matching classification state
4. assign priority buckets and sort key

### Ongoing incremental flow

After each successful metadata refresh batch:

1. inspect touched or updated files
2. detect whether they now require classification or reclassification
3. enqueue missing jobs if no active or already-satisfied state exists

This must run in parallel with metadata ingestion, not instead of it.

## Worker Model

Add a dedicated classification submission worker path inside `iCloudPlugin`.

### Concurrency

- default concurrency: `2`
- configurable max: `4`

Suggested env vars:

- `CLASSIFIER_API_URL`
- `CLASSIFIER_API_TOKEN`
- `CLASSIFICATION_SUBMISSION_ENABLED`
- `CLASSIFICATION_SUBMISSION_CONCURRENCY`
- `CLASSIFICATION_SUBMISSION_POLL_INTERVAL_SECONDS`
- `CLASSIFICATION_MAX_ATTEMPTS`

### Queue behavior

- claim queued jobs one at a time per worker slot
- update heartbeat while upload/classification is in progress
- requeue transient failures with backoff
- fail permanently after max attempts
- do not block metadata refresh jobs

The existing refresh job framework may be extended, but classification jobs
should not share the same single-active constraint as refresh jobs.

## Classifier API Contract

Target endpoint:

- `POST http://192.168.50.196:4319/classify/upload`

Headers:

- `X-API-Key: <CLASSIFIER_API_TOKEN>`

Payload:

- multipart full-file upload
- include stable original filename
- use `ingestion_mode=real-folder`

Expected success handling:

- HTTP success response from the classifier API marks the submission job
  completed
- response payload fields such as manifest record, summary, timing, and note
  path are persisted into `classification_states`

V1 completion contract:

- classifier API success is the primary success condition
- vault note existence is not the blocking completion rule
- later reconciler work can verify note existence and heal drift

## File Access

`iCloudPlugin` should submit files from the already indexed mirrored filesystem:

- current source tree on `192.168.50.232`:
  `/srv/cloud-vault/mirrors/icloud`

The submission worker must resolve the indexed `path` back to the mirrored host
path safely and verify the file exists before upload.

If the file is missing locally:

- record a retriable submission error first
- do not synthesize a fake success

## Failure Handling

Transient failure examples:

- classifier API unreachable
- timeout
- HTTP 5xx
- temporary file-read failure

Permanent failure examples:

- file missing repeatedly
- unsupported file type by policy
- HTTP 4xx indicating invalid request or blocked ingestion

Required behavior:

- surface failure reason in job row and state row
- preserve enough detail for operator debugging
- avoid duplicate active jobs during retries

## Retrieval Linkage

Persist enough classifier response data so later ChatGPT retrieval can prefer
note-first answers:

- vault-relative note path
- summary
- primary label
- confidence
- manifest payload

This enables the future retrieval cascade:

1. Obsidian note
2. indexed extracted text
3. raw original file

## Testing

Add focused tests for:

- high-value priority ordering
- backfill job creation from already indexed files
- incremental enqueue for changed files
- duplicate suppression when an active job already exists
- submission success persistence into `classification_states`
- retry and permanent failure behavior
- compose/env wiring for classifier settings
- parallel operation without breaking refresh-job behavior

Validation commands should include:

- targeted classification submission tests
- full `pytest`
- `docker compose config`

## Operational Notes

The rollout is configuration-sensitive:

- `192.168.50.232` runs `iCloudPlugin`
- `192.168.50.196` hosts the classifier API and GPU
- `192.168.50.86` hosts the vault and mirror storage

The classifier must remain ready for real-folder ingestion if the API enforces
that mode. If readiness blocks `real-folder` ingestion, this rollout must
either:

- explicitly enable it on the classifier host, or
- temporarily use `adhoc` while preserving the same full-file path

That decision should be made during implementation validation, not hidden.

## Out of Scope

Not part of this rollout:

- direct note reading APIs from the classifier into ChatGPT
- full-vault free-text retrieval mode
- metadata-first shortcut classification
- autonomous file moving or renaming
- video or audio transcription
- vault reconciliation worker beyond basic stored response linkage
