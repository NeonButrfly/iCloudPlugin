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
  - use on the sync/index/API compute host such as `tichuml1`
  - keep storage authoritative on `kayraspi2`
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

For a compute-only deployment where `tichuml1` mounts the shared storage from
`kayraspi2`:

- set `ICLOUD_SOURCE_MODE=filesystem-mirror`
- set `ICLOUD_MIRROR_MOUNT_SOURCE=/mnt/cloud-vault`
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
- the OCR path is now image-first and cheap by default:
  - image files try PaddleOCR when available, then fall back to Tesseract
  - scanned PDFs fall back to page-render OCR when native PDF text is sparse
- the classifier runtime image now installs the CPU PaddlePaddle runtime ahead
  of `paddleocr`, so the faster OCR path is present in normal container builds
- `ICLOUD_PADDLE_OCR_ENABLED` controls whether the optional PaddleOCR path is attempted before Tesseract
- `ICLOUD_PDF_NATIVE_TEXT_MIN_CHARS` controls when a PDF is considered too text-sparse and should be OCRed
- `ICLOUD_PDF_OCR_MAX_PAGES` bounds how many rendered PDF pages are OCRed per file
- `ICLOUD_PDF_OCR_DPI` controls PDF page render resolution for OCR fallback
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
- it submits mirror-relative source paths to `CLASSIFIER_API_URL` using
  `CLASSIFIER_API_TOKEN` for normal real-folder ingestion, so the classifier
  reads the shared source file directly instead of staging a duplicate upload
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
- that reconciliation pass now also realigns `classification_states.classifier_note_path`
  plus stored manifest/response note references to the preferred current vault
  note when note convergence has already collapsed duplicate `(2)` or `(3)`
  variants (#35)
- the same reconciliation layer can now repair stale owned source-link fields
  in existing generated notes without a full reset (#41)
  - `source_link`
  - `attachment`
  - the rendered `## Original File` section
- that same bounded reconciliation pass now also backfills missing
  classifier-context frontmatter in older generated notes from stored
  classification state, including:
  - `source_parser`
  - `heuristic_primary_hint`
  - `hybrid_live_source`
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
- `IMAGE_OCR_MIN_CHARS` controls when an image is routed through the OCR-backed
  document path instead of going straight to Qwen vision fallback.
- the classifier role now also needs a read-only shared-source mount:
  - `CLASSIFIER_SOURCE_MOUNT_SOURCE` should point at the host mirror root
  - `CLASSIFIER_SOURCE_ROOT` is the in-container mount path, default `/source`
  - on `tichuml1`, this host mount should usually point at the shared mirror
    path under `/mnt/cloud-vault/mirrors`
  - keep `ICLOUD_MIRROR_ROOT` aligned with the canonical note paths,
    typically `/srv/cloud-vault/mirrors`, even when the host-visible mount
    comes from `/mnt/cloud-vault/mirrors`
  - manual generated-note feedback now translates canonical mirror paths such
    as `/srv/cloud-vault/mirrors/...` and `/mnt/cloud-vault/mirrors/...` back
    into `CLASSIFIER_SOURCE_ROOT` before trying to re-parse the source file, so
    legacy moved notes can recover parser context inside the classifier
    container instead of falling back to `obsidian-generated-note`
  - manual generated-note moves are now also treated as effective reviewed
    feedback when the primary label stays the same but the folder move adds or
    changes meaningful secondary labels such as `medical/appeals`
  - exact reviewed overrides now prefer a same-source correction over a newer
    same-filename row from the reviewed corpus, which matters for common names
    like `Appeal.docx`
  - this feedback loop is now proven live across five parser-plus-hint
    families:
    - `pdf-ocr-tesseract|unknown`
    - `docx-xml|unknown`
    - `plain-text|unknown`
    - `spreadsheet-openpyxl|spreadsheet`
    - `docling|unknown`
- on `kayraspi`, ad hoc `docker compose` runs for the `cloudsync` role should
  use the live project name explicitly:
  - use `-p icloudplugin`
  - otherwise Docker Compose derives `cloudsync` from the role directory and
    tries to start a second `postgres` container on host port `5432`
- for a bounded live backfill pass, prefer a one-shot worker run instead of
  enabling the long-running service immediately:

```powershell
Set-Location /opt/iCloudPlugin
sudo docker compose -p icloudplugin --env-file .env `
  -f deploy/roles/cloudsync/docker-compose.yml run --rm --no-deps `
  -e CLASSIFICATION_SUBMISSION_CONCURRENCY=2 `
  classification-worker `
  uv run python -c "from icloud_index_service.classification_worker import run_classification_worker_loop; print(run_classification_worker_loop(max_polls=3, poll_interval_seconds=0.1))"
```

For the preferred compute-only cutover to `tichuml1`, start the long-running
cloudsync stack with the host-local mount path instead of the old read-only Pi
mount:

```bash
cd /opt/iCloudPlugin
cp deploy/roles/cloudsync/.env.tichuml1.example deploy/roles/cloudsync/.env.live
# then set the real secrets in deploy/roles/cloudsync/.env.live
sudo docker compose -p icloudplugin \
  --env-file deploy/roles/cloudsync/.env.live \
  -f deploy/roles/cloudsync/docker-compose.yml \
  up -d --build postgres migrate service worker
```

Recommended first cutover values in `deploy/roles/cloudsync/.env.live`:

- `POSTGRES_HOST=192.168.50.232`
- `POSTGRES_PORT=5432`
- `ICLOUD_MIRROR_MOUNT_SOURCE=/mnt/cloud-vault`
- `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors`

That keeps the existing Postgres on `kayraspi` for the first compute move
while shifting the expensive API and refresh worker load onto `tichuml1`.

- for repeated targeted batches such as `Scanned`-first passes, prefer the
  helper script added in issue [#36](https://github.com/NeonButrfly/iCloudPlugin/issues/36):

```bash
  cd /opt/iCloudPlugin
  FOCUS_PREFIX=/icloud/Scanned/ \
  DEFER_PREFIX=/icloud/Downloads/ \
  ./deploy/roles/cloudsync/run_targeted_classification_batch.sh \
    --run-live-summary \
    --summary-json /tmp/targeted-batch-summary.json
  ```
  
  - the helper prints before/after queue counts, can temporarily defer one queued
    path prefix, runs the bounded worker with a configurable timeout, restores
    deferred jobs automatically during cleanup, and can print the newest
    completed rows explicitly after the batch with `--run-live-summary`
  - add `--targeted-feedback-only` when you want the bounded run to process
    strong manual-feedback requeues plus reconciliation without seeding broader
    backfill work
  - when `--summary-json` is provided, the helper also writes a machine-readable
    artifact with before/after counts, queue previews, recent completions, and
    timeout status for the bounded run
  - on the compute-only `tichuml1` deployment, the helper now talks to the
    configured remote Postgres through a disposable `postgres:16` client
    container instead of requiring a local compose `postgres` service

- if a bounded run is interrupted, or a long file is intentionally stopped
  mid-pass, recover stale `running` jobs before the next batch:

```powershell
Set-Location /opt/iCloudPlugin
sudo docker compose -p icloudplugin --env-file .env `
  -f deploy/roles/cloudsync/docker-compose.yml run --rm --no-deps `
  classification-worker `
  uv run python -c "from icloud_index_service.db import get_session_factory; from icloud_index_service.services.classification_submission import recover_stale_running_classification_jobs; session = get_session_factory()(); print(recover_stale_running_classification_jobs(session, stale_after_seconds=0)); session.close()"
```

Ad hoc uploads still use the upload endpoint, but the temporary staged copy is
deleted immediately after classification finishes, even on failures.

To repair existing generated notes in place after the Windows UNC source-link
change, run the file-only repair helper on the writable classifier host:

```bash
cd /opt/iCloudPlugin
docker compose --env-file .env \
  -f deploy/roles/classifier/docker-compose.yml run --rm --no-deps \
  classifier-api \
  uv run python -c "from pathlib import Path; from icloud_index_service.services.vault_reconciliation import repair_vault_source_links; print(repair_vault_source_links(Path('/mnt/cloud-vault/document-vault')))"
```

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
For cloud-vault mirror files, the generated source link now defaults to a
Windows UNC share path such as `\\192.168.50.86\cloud-vault\mirrors\...` so the
link opens naturally from the Windows workflow.

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

For image-heavy and scan-heavy files, the classifier now prefers cheap OCR
evidence first and only falls back to Qwen vision when the extracted text is
too sparse to support the document pipeline.

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

## Classifier readiness bootstrap and autonomous shadow learning

The classifier role now treats `/config` as an operator-provided input mount,
not as the only writable home for active model state (#28).

Runtime behavior:

- bundled seed artifacts live in the image under `/app/config`
- active writable classifier artifacts live under `/output/_artifacts`
- on startup and readiness checks, the runtime bootstraps missing writable
  copies of:
  - `hybrid-gating.json`
  - `heuristic-rules.json`
  - `lightgbm-classifier.joblib`
  - `lightgbm-training-report.json`
  - `taxonomy-router.joblib`
  - `taxonomy-router-report.json`
- if the active LightGBM model is still missing after bootstrap, the runtime
  retrains it from the reviewed runtime corpus or the live index fallback

Readiness behavior:

- `/readiness` now refreshes the report on demand instead of serving a stale
  file forever
- readiness counts both:
  - Qwen shadow-comparison approvals from `shadow-comparisons.jsonl`
  - reviewed bootstrap examples from `examples.jsonl` and `corrections.jsonl`
- this removes the old catch-22 where real-folder ingestion was blocked until
  shadow approvals existed, even though a reviewed teacher corpus was already
  available

Self-training loop:

- heuristics participate through disagreement-driven `force_inline_llm_for`
  updates and threshold tuning
- LightGBM participates through retraining on the merged approved feedback set
- Qwen participates as the shadow teacher that reviews live decisions from the
  shadow queue
- the classifier role now has a dedicated `shadow-worker` service; do not rely
  on the API's in-process background thread when `uvicorn` is running multiple
  workers
- malformed or non-JSON Qwen shadow responses are now recorded as
  `shadow-error` comparison rows and removed from the queue so one bad teacher
  response cannot wedge the autonomous loop
- malformed structured live-classifier payloads that omit `primary_label` or
  `confidence` are now normalized before note writing (#32)
  - if LightGBM or heuristic hybrid hints provide a sensible fallback label, the
    note keeps that recovered label but stays under `02 Needs Review`
  - if no safe fallback exists, the note degrades to `needs-review` instead of
    an opaque `unknown` label
- the dedicated `shadow-worker` also needs the shared source mirror mount, not
  just `classifier-api`, because image review jobs reopen the original file
  directly from `/source`
- the Qwen teacher prompts now explicitly forbid markdown fences, numbered
  lists, or prose outside the JSON object, and the runtime JSON extractor now
  tolerates fenced or prefixed JSON responses before declaring `shadow-error`
- the dedicated `shadow-worker` also scans manual user-authored Obsidian notes
  outside generated classifier folders and exports changed notes into
  `manual-note-feedback.jsonl` (#42)
  - supported manual signals come from note edits plus optional frontmatter such
    as `primary_label`, `canonical_source_path`, and `source_file`
  - these exported rows count as bootstrap feedback for readiness and LightGBM
    retraining, so real user curation in Obsidian can improve the classifier
    without waiting for a replayed live classification
- manual vault organization now contributes two more classifier signals (#43)
  - folder paths can act as weak labels when they map cleanly to known
    classifier categories
  - moving classifier-generated notes into a different folder can act as a
    stronger correction signal keyed back to the original source file
- strong manual corrections now also trigger targeted backend reclassification
  for the matching source file (#44)
  - only strong corrections participate; weak folder-label hints stay in the
    training set and do not requeue the source file immediately
  - the worker only requeues when the note edit is newer than the last
    completed classification for that source, which prevents repeat loops
  - when the classifier sees the exact same source path again, reviewed manual
    feedback now wins immediately as a deterministic override instead of being
    treated only as future training signal
  - generated notes now persist the original source parser plus heuristic hint
    in frontmatter, and the shadow worker exports those fields back into
    strong manual-feedback rows before running its retrain/update pass
  - if an older generated note move is missing that classifier-context
    frontmatter and no longer has recoverable state payloads, the manual-note
    export now derives parser and heuristic-hint context from the live source
    file itself so the correction can still train LightGBM and heuristic
    gating instead of falling back to `obsidian-generated-note`
  - fresh approved manual-note rows now bypass the generic
    `auto_retrain_min_new_rows` gate so a real new manual correction can force
    a LightGBM retrain even when the broader teacher corpus only grew by a
    couple of rows
  - those enriched manual-feedback rows now participate in heuristic
    fast-path learning by adding `force_inline_llm_for` rules when repeated
    human corrections show a parser plus heuristic-hint combination is unsafe
  - live proof on 2026-05-29 AKDT: four real generated-note moves in the
    `pdf-ocr-tesseract|unknown` family caused the runtime to append strong
    manual-feedback rows, retrain LightGBM from `542 -> 546` teacher-approved
    rows, and grow `force_inline_llm_for` to include
    `pdf-ocr-tesseract|unknown`
  - live proof on 2026-05-30 AKDT: three real spreadsheet note moves in the
    `spreadsheet-openpyxl|spreadsheet` family moved:
    - `MDM Enrollment DNS and Ports.xlsx` from `spreadsheet` to `technical`
    - `capital_gains_2024.xlsx` from `spreadsheet` to `financial`
    - `Actions Taken.xlsx` from `spreadsheet` to `medical/appeals`
    the live shadow-worker then exported `4` fresh manual-note rows, retrained
    LightGBM from `631 -> 641` approved teacher rows, and grew
    `force_inline_llm_for` to include `spreadsheet-openpyxl|spreadsheet`
  - live downstream proof on 2026-05-30 AKDT: rerunning direct classification
    for those same spreadsheet sources then landed them at:
    - `01 Classified/technical/MDM Enrollment DNS and Ports - technical.md`
    - `01 Classified/financial/capital_gains_2024 - financial.md`
    - `01 Classified/medical/appeals/Actions Taken - medical - appeals.md`
    with `hybrid_live_source="manual-correction-override"`
  - live proof on 2026-05-30 AKDT: three real HTML note moves in the
    `docling|unknown` family moved:
    - `Request Denial Information.html` from `medical` to `insurance`
    - `your_messages.html` from `financial` to `personal`
    - `comments.html` from `insurance` to `personal`
    the live shadow-worker then exported `4` fresh manual-note rows, retrained
    LightGBM from `657 -> 660` approved teacher rows, and grew
    `force_inline_llm_for` to include `docling|unknown`
  - live downstream proof on 2026-05-30 AKDT: rerunning direct classification
    for those same HTML sources then landed them at:
    - `01 Classified/insurance/Request Denial Information - insurance.md`
    - `01 Classified/personal/your_messages - personal.md`
    - `01 Classified/personal/comments - personal.md`
    with `hybrid_live_source="manual-correction-override"`
  - historical generated-note rows where `correct_label == old_label` are now
    ignored by bootstrap feedback import, so stale no-op rewrites do not count
    as teacher corrections for readiness, LightGBM retraining, or heuristic
    gating updates
  - `CLASSIFICATION_TARGETED_REQUEUE_ENABLED` and
    `CLASSIFICATION_TARGETED_REQUEUE_LIMIT` bound this behavior
  - set `CLASSIFICATION_BACKFILL_ENABLED=false` when you want a bounded worker
    run to process only manual-feedback requeues plus reconciliation
- explicit folder-to-label overrides live in:
  - `config/vault-folder-labels.json`
  - use this when a human-facing vault folder name should map to a canonical
    classifier label such as `receipts -> receipt` or
    `medical/appeals -> medical + appeal`

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

## OCR-rich classifier feature text

Issue [#27](https://github.com/NeonButrfly/iCloudPlugin/issues/27) promotes OCR
quality into the classifier runtime and training rows instead of treating OCR as
an opaque text source.

Current behavior:

- the classifier runtime image installs `paddlepaddle` plus `paddleocr` during
  the normal Docker build, so PaddleOCR is available in the shipped container
- image OCR and scanned-PDF OCR now preserve:
  - `ocr_engine`
  - `ocr_quality`
  - `ocr_char_count`
  - `extraction_quality`
- those fields now flow into:
  - live LightGBM feature text
  - shadow comparison rows
  - runtime-manifest retraining rows

That means weak OCR can now lower model confidence or push borderline files back
toward the inline teacher path instead of only shortening the extracted text.

## Retrieval-first vault intelligence

Issue [#26](https://github.com/NeonButrfly/iCloudPlugin/issues/26) shifts the
classifier into a support role for retrieval instead of treating it as the
single source of truth.

Current retrieval flow:

- classifier submissions now persist `entity_summary`, `topic_summary`,
  `retrieval_terms`, and `retrieval_text` on `classification_states`
- `/search` and `/files/{id}` surface those fields so the index can find
  misfiled documents by entity, topic, or semantic hints instead of only
  filename/path text
- generated Obsidian notes and `Classification Index.md` now expose discovery
  topics and entities for the same files
- the `0005_classification_retrieval_metadata` migration now widens
  `alembic_version.version_num` before applying the retrieval-metadata schema
  change, so older hosts still using the legacy `VARCHAR(32)` version column can
  upgrade cleanly without a manual pre-alter (#30)

Current self-learning flow:

- live classifications keep the richer retrieval evidence in manifest rows and
  shadow-queue payloads
- the classifier's existing shadow worker now processes queued teacher checks
  in bounded batches
- `auto_threshold_update_enabled` controls whether disagreement-driven heuristic
  gating updates are applied automatically
- `auto_retrain_enabled` controls whether approved shadow comparisons can
  retrain LightGBM automatically
- `shadow_batch_size`, `auto_retrain_min_rows`, and
  `auto_retrain_min_new_rows` bound how much the autonomous loop does per cycle

Useful checks:

```bash
python -m apps.classifier.classify_to_obsidian --write-readiness-report
```

```bash
python -m apps.classifier.classify_to_obsidian --process-shadow-queue
```

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
CLASSIFICATION_BACKFILL_ENABLED=true
CLASSIFICATION_SUBMISSION_POLL_INTERVAL_SECONDS=5
CLASSIFICATION_MAX_ATTEMPTS=3
CLASSIFICATION_RETRY_BACKOFF_SECONDS=0
CLASSIFIER_SOURCE_ROOT=/source
CLASSIFIER_SOURCE_MOUNT_SOURCE=/mnt/cloud-vault/mirrors
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
