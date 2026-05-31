# Chat Handoff

Canonical workspace is `C:\Code\iCloudPlugin`.

## What This Project Is

- `iCloudPlugin` is the canonical monorepo for the cloud-vault platform.
- It contains the iCloud connector, sync/index/API side, classifier side, shared packages, and deployment roles.
- `C:\Code\local-doc-classifier` is legacy/transitional and is not the source of truth.

## Live Host Layout

- `kayraspi` (`192.168.50.232`)
  - transitional legacy `iCloudPlugin` host
  - still hosts the live cloudsync Postgres database during the compute-only cutover
  - repo path: `/opt/iCloudPlugin`
  - mounts `/srv/cloud-vault` from `kayraspi2` as read-only NFS

- `tichuml1` (`192.168.50.196`)
  - live classifier host
  - live sync/index/API compute host
  - repo path: `/opt/iCloudPlugin`
  - main service port: `8080`
  - classifier API port: `4319`
  - mounts shared vault from `kayraspi2` at `/mnt/cloud-vault`

- `kayraspi2` (`192.168.50.86`)
  - storage/share/proxy host
  - local storage root: `/srv/cloud-vault`
  - runs NFS, SMB, Caddy, iCloud mirror sync, and iPhone backup timers

- `tichuml` (`192.168.50.36`)
  - Tichu backend/Postgres host
  - not part of the cloud-vault runtime path

## Important Paths

- canonical repo:
  - `C:\Code\iCloudPlugin`

- workspace map:
  - `C:\Code\iCloudPlugin\docs\workspace-map.md`

- architecture discovery bundle:
  - `C:\Code\iCloudPlugin\docs\architecture-discovery\architecture-discovery-20260518-1856-AK`

- canonical live vault path:
  - `/srv/cloud-vault/document-vault`

- legacy compatibility vault path:
  - `/srv/cloud-vault/local-doc-classifier-vault` -> `document-vault`

## What Was Completed

- shared SSH key access was installed for all four hosts
- `tichuml1` classifier service was cut over to the monorepo deployment from `/opt/iCloudPlugin`
- `kayraspi` `/opt/iCloudPlugin` was updated to current `main` and rebuilt
- the old `New project 2` architecture artifacts were moved into repo docs
- the repo now has a canonical workspace map and consolidated artifact location

## Important Deployment Fixes Already Made

- the classifier image was fixed to include the shared `packages/` tree
- the classifier image was fixed to use `CMD` instead of `ENTRYPOINT` so API startup override works
- the classifier API role was hardened for live traffic:
  - `ENABLE_SHADOW_WORKER=0` by default in the API role
  - four Uvicorn workers in the classifier API role
- on `kayraspi`, `CLASSIFIER_VAULT_RECONCILIATION_ENABLED=false` is intentional when that host is using the read-only NFS mount from `kayraspi2`

## Current Status

- `tichuml1` `iCloudPlugin` health is OK on `127.0.0.1:8080`
- `tichuml1` `/refresh/status` is still running the active aggregate
  background scan
- live `/refresh/status` on 2026-05-30 AKDT shows:
  - `status=running`
  - `job_id=12`
  - `job_type=metadata-refresh`
  - `source=background-scan`
  - `items_seen=1700`
  - `batch_count=17`
  - `frontier_length=2218`
  - `error_message=null`
- `clouddrive.neonbutterfly.net` now proxies to `192.168.50.196:8080`
- `tichuml1` classifier health is OK
- `tichuml1` classifier containers were recreated from the monorepo compose on
  2026-05-29 AKDT while preserving the existing trained runtime/output
  directories under `/opt/local-doc-classifier` for continuity
- the repo now contains the first Cloudflare remote MCP slice under
  `cloudflare/remote-mcp` from issue
  [#48](https://github.com/NeonButrfly/iCloudPlugin/issues/48)
  - the on-prem service now has plugin-token-protected file/note/source routes:
    - `GET /files/{id}`
    - `GET /files/{id}/note`
    - `GET /files/{id}/source`
    - `GET /files/{id}/source/download`
  - the repo-local MCP bridge now exposes:
    - `search_icloud_notes_and_files`
    - `get_icloud_note`
    - `get_icloud_source_reference`
    - `get_icloud_file_bundle`
  - the combined search tool now searches once and hydrates the top matches
    into bundled file/note/source payloads so external ChatGPT callers do not
    need to stitch multiple follow-up calls together for common analysis flows
  - that combined retrieval path is now also first-class on the origin service
    through `GET /search/bundles`, so both the local bridge and the Cloudflare
    Worker reuse the same bundle assembly path
  - the Cloudflare Worker scaffold proxies those same surfaces and can hand off
    original files through `/download/{file_id}`
  - the Worker now also supports an optional client-facing bearer gate via
    `WORKER_API_TOKEN` and exposes non-secret health metadata at `/` and
    `/healthz` for deployment verification
  - repo-local operator helpers now exist in `cloudflare/remote-mcp/scripts`:
    - `deploy-and-verify.mjs` plans/deploys/verifies the Worker without relying
      on remembered Wrangler flags
    - `print-access-bootstrap.mjs` emits ready-to-run Cloudflare Access
      bootstrap commands for the recommended self-hosted Access model
    - `.dev.vars.example` documents the local Worker secret shape for
      `wrangler dev`
  - this slice was validated locally with Python tests plus Worker TypeScript
    type-check
  - the on-prem origin half of the slice is now deployed live on `tichuml1`
    as of 2026-05-31 AKDT:
    - `/search`, `POST /refresh`, and `/files/*` enforce bearer auth
    - `GET /files/{id}/note` is live
    - `GET /files/{id}/source` is live
    - `GET /files/{id}/source/download` is live
    - live sample file `23` proved canonical source metadata and UNC
      `source_link` output; `note_available` was correctly `false` because the
      generated vault surfaces had been cleared before fresh ingestion
  - Cloudflare account-side deployment is still **not** validated because:
    - `npx wrangler whoami` reports `Not logged in`
    - non-interactive Cloudflare deploy/list flows require
      `CLOUDFLARE_API_TOKEN`
  - follow-up bug [#49](https://github.com/NeonButrfly/iCloudPlugin/issues/49)
    is now fixed in repo, repaired live on `tichuml1`, and closed:
    - the live cloudsync env had `CLASSIFIER_API_TOKEN` blank, which broke
      real-folder classifier submission with classifier API `401`
    - the token is now synced from the classifier role env
    - the cloudsync `classification-worker` is running again
    - fresh smoke file `8213`
      (`/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx`) completed
      successfully and regenerated:
      - `01 Classified/medical/appeals/Aetna Life Insurance Company - APPEAL 1 FFS - medical - appeals.md`
      - `attachment_mode=canonical-source-link`
      - UNC `source_link` back to `\\192.168.50.86\cloud-vault\mirrors\google1\...`
      - `/files/8213/note` now returns `note_available=true`
      - `90 Attachments` stayed at `0` files during the smoke proof
- live classifier readiness recovered and is green again:
  - `model_exists=true`
  - `real_ingestion_allowed=true`
  - `teacher_reviewed_rows=569`
  - `teacher_approved_rows=546`
  - `feedback_sources.manual-obsidian-note=22`
- a one-shot `shadow-worker` run on 2026-05-29 AKDT scanned `39` vault notes,
  exported `1` fresh manual-feedback row from a real note move, and retrained
  LightGBM live with `training_rows=545`
- the live manual-feedback artifact now includes the receipt correction for
  `/srv/cloud-vault/mirrors/icloud/Scanned/03182023_You for Shopping at Lowe’s your new purchase!.pdf`
  with `correct_label=receipt` and `old_label=financial`
- a direct bounded cloudsync classification-worker run created and completed
  targeted job `#55` for that same receipt source file
- the classifier now honors strong reviewed corrections by canonical source path
  and ignores no-op generated-note feedback rows where `correct_label` matches
  `old_label`
- after the follow-up live redeploy on 2026-05-29 AKDT, the same receipt source
  now rewrites correctly to:
  `01 Classified/receipt/03182023_You for Shopping at Lowe’s your new purchase! - receipt.md`
  with `primary_label="receipt"` and `confidence=1.0`
- generated notes now also persist `source_parser` and `hybrid_live_source`
  frontmatter for future manual-feedback export; a live receipt reclassification
  on 2026-05-29 AKDT confirmed:
  - `source_parser="pdf-ocr-tesseract"`
  - `hybrid_live_source="manual-correction-override"`
- `fix: ignore stale no-op bootstrap feedback` was deployed live on
  2026-05-29 AKDT, and a forced LightGBM retrain then rebuilt the model from
  the cleaned teacher set:
  - `teacher_reviewed_rows=565`
  - `teacher_approved_rows=540`
  - `feedback_sources.manual-obsidian-note=4`
  - `feedback_sources.reviewed-example=500`
  - `feedback_sources.shadow-qwen=36`
  - LightGBM `training_rows=540`
  - LightGBM `class_count=18`
  - LightGBM `trained_at=2026-05-30T05:58:03Z`
- the shadow worker now syncs manual note feedback before running its
  retrain/update pass, and manual-feedback rows with real parser context can
  now contribute to `force_inline_llm_for` heuristic gating updates
- the bounded vault reconciliation pass now also backfills missing
  `source_parser`, `heuristic_primary_hint`, and `hybrid_live_source`
  frontmatter in older generated notes from stored classification-state
  payloads, so pre-existing manual note moves can export richer training
  signals without recreating the note first
- a bounded live reconciliation pass on 2026-05-29 AKDT repaired `24` out of
  `25` completed-state notes scanned and reduced generated notes missing that
  newer classifier-context frontmatter from `42` to `19`
  - the remaining `19` split cleanly into:
    - `7` notes whose matching `classification_state` rows are still `queued`
    - `12` notes with no surviving `classification_state` row to recover from
- after `feat: derive legacy feedback context from source files`, a live
  `shadow-worker` smoke run on 2026-05-29 AKDT also proved that a moved legacy
  generated note with no stored classifier context now exports derived
  `parser` and `heuristic_primary` values directly from the source file itself
  (`plain-text` + `legal` in the smoke case) instead of falling back to
  `obsidian-generated-note`
- after `fix: retrain from fresh manual feedback`, a live `shadow-worker` pass
  on 2026-05-29 AKDT retrained LightGBM immediately from `2` fresh manual
  teacher rows even though the broader corpus growth was still below the old
  `min_new_rows_since_last_train` gate
  - resulting live retrain report:
    - `retrained=true`
    - `training_rows=542`
    - `new_teacher_rows=2`
    - `new_manual_teacher_rows=2`
    - `trained_at=2026-05-30T06:35:42Z`
  - live heuristic rules still did **not** expand beyond
    `pdftotext|unknown`; current manual-note feedback artifact only contains
    one effective strong generated-note move pair, so the heuristic-update
    path is now code-ready but still signal-limited in live data
- after four additional real generated-note moves on 2026-05-29 AKDT in the
  `pdf-ocr-tesseract|unknown` family, the live `shadow-worker` finally proved
  the heuristic-learning path end to end:
  - strong manual-note rows grew from `1` to `5`
  - LightGBM retrained again from `542` to `546` approved teacher rows
  - live heuristic rules now include:
    - `pdftotext|unknown`
    - `pdf-ocr-tesseract|unknown`
  - readiness remained green with:
    - `teacher_reviewed_rows=571`
    - `teacher_approved_rows=546`
    - `feedback_sources.manual-obsidian-note=10`
    - `real_ingestion_allowed=true`
- after `fix: translate canonical feedback sources into classifier mount`, the
  live classifier role on `tichuml1` now also preserves parser recovery for
  canonical mirror paths that are only host-visible through the shared source
  mount:
  - `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors` is now passed into the
    classifier API and shadow-worker roles alongside `CLASSIFIER_SOURCE_ROOT`
  - a live probe inside `cloud-vault-classifier-shadow-worker` on
    2026-05-29 AKDT confirmed both
    `/srv/cloud-vault/mirrors/google1/Codex-Multi-Drive-Probe/google-drive-submission-test.txt`
    and
    `/mnt/cloud-vault/mirrors/google1/Codex-Multi-Drive-Probe/google-drive-submission-test.txt`
    now resolve to the mounted source tree and return:
    - `parser="plain-text"`
    - `heuristic_primary="unknown"`
    - `hybrid_live_source=""`
  - before that fix, the same helper path was falling back to
    `parser="obsidian-generated-note"` for those legacy-style canonical paths
- after three real manual moves on 2026-05-29 AKDT in the `docx-xml|unknown`
  family:
  - `Appeal.docx` -> `02 Needs Review/appeal/...`
  - `2024-08-27 Kay Myers Internal Appeal Draft.docx` -> `02 Needs Review/appeal/...`
  - `2023.GAS.Appeal.Template.and.Instructions.Final.docx` ->
    `02 Needs Review/appeal-template/...`
  the live manual-feedback artifact gained three new strong manual-note rows,
  all with:
  - `parser="docx-xml"`
  - `heuristic_primary="unknown"`
  - `hybrid_live_source="inline-llm"`
  - `old_label="medical"`
  and the classifier runtime then proved a second live heuristic-learning
  family beyond PDFs:
  - `force_inline_llm_for` now includes `docx-xml|unknown`
  - LightGBM retrained live to `training_rows=553`
  - readiness stayed green with `feedback_sources.manual-obsidian-note=13`
- after `fix: prefer exact manual override over filename collisions`, exact
  same-source reviewed feedback now beats newer reviewed-example rows that only
  share a filename; this fixed a real live `Appeal.docx` collision where a
  different reviewed example had been masking the manual correction
- after `feat: learn secondary label moves from vault curation`, generated-note
  manual feedback now remains effective when the primary label stays the same
  but the folder move adds a meaningful secondary label such as
  `medical/appeals`
- live proof on 2026-05-29 AKDT:
  - moved `Appeal - medical.md` into
    `01 Classified/medical/appeals/Appeal - medical - appeals.md`
  - ran manual-note sync to export the new same-primary secondary-label
    correction row
  - reran direct classification for `/srv/cloud-vault/mirrors/google1/Appeal.docx`
  - resulting note now lands at:
    `01 Classified/medical/appeals/Appeal - medical - appeals.md`
  - verified frontmatter now shows:
    - `primary_label="medical"`
    - `secondary_labels=["appeal"]`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `plain-text|unknown` family:
  - `google-drive-submission-test.txt` moved from `financial` to `technical`
  - `GE76_Raider_11UE(20230913).txt` moved from `letter` to `technical`
  - `twilio_2FA_recovery_code.txt` moved from `medical` to `technical`
  the live runtime then proved a third heuristic-learning family:
  - `force_inline_llm_for` now includes `plain-text|unknown`
  - LightGBM retrained live again to `training_rows=624`
  - readiness remained green with `feedback_sources.manual-obsidian-note=79`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/untitled folder/Downloads/twilio_2FA_recovery_code.txt`
  - resulting note now lands at:
    `01 Classified/technical/twilio_2FA_recovery_code - technical.md`
  - verified frontmatter now shows:
    - `primary_label="technical"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `spreadsheet-openpyxl|spreadsheet` family:
  - `MDM Enrollment DNS and Ports.xlsx` moved from `spreadsheet` to
    `technical`
  - `capital_gains_2024.xlsx` moved from `spreadsheet` to `financial`
  - `Actions Taken.xlsx` moved from `spreadsheet` to `medical/appeals`
  the live runtime then proved a fourth heuristic-learning family:
  - `force_inline_llm_for` now includes `spreadsheet-openpyxl|spreadsheet`
  - LightGBM retrained live from `631` to `641` approved teacher rows
  - readiness remained green with:
    - `teacher_reviewed_rows=683`
    - `teacher_approved_rows=641`
    - `feedback_sources.manual-obsidian-note=89`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/MDM Enrollment DNS and Ports.xlsx`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/capital_gains_2024.xlsx`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/FFS/Actions Taken.xlsx`
  - resulting notes now land at:
    - `01 Classified/technical/MDM Enrollment DNS and Ports - technical.md`
    - `01 Classified/financial/capital_gains_2024 - financial.md`
    - `01 Classified/medical/appeals/Actions Taken - medical - appeals.md`
  - verified frontmatter on each now shows:
    - `source_parser="spreadsheet-openpyxl"`
    - `heuristic_primary_hint="spreadsheet"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `docling|unknown` family:
  - `Request Denial Information.html` moved from `medical` to `insurance`
  - `your_messages.html` moved from `financial` to `personal`
  - `comments.html` moved from `insurance` to `personal`
  the live runtime then proved a fifth heuristic-learning family:
  - `force_inline_llm_for` now includes `docling|unknown`
  - LightGBM retrained live from `657` to `660` approved teacher rows
  - readiness remained green with:
    - `teacher_reviewed_rows=705`
    - `teacher_approved_rows=660`
    - `feedback_sources.manual-obsidian-note=101`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/FFS/Request Denial Information.html`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google2/meta-2025-May-02-05-47-46/facebook-kaymayers49-2025-05-02-6iqlH3mC/your_facebook_activity/messages/your_messages.html`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google2/meta-2025-May-02-05-47-46/facebook-kaymayers49-2025-05-02-6iqlH3mC/your_facebook_activity/comments_and_reactions/comments.html`
  - resulting notes now land at:
    - `01 Classified/insurance/Request Denial Information - insurance.md`
    - `01 Classified/personal/your_messages - personal.md`
    - `01 Classified/personal/comments - personal.md`
  - verified frontmatter on each now shows:
    - `source_parser="docling"`
    - `heuristic_primary_hint="unknown"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `docling-converted|unknown` family:
  - `B217C1 Buff Parchment.doc` moved from `medical` to `personal`
  - `Kay Vaginoplasty GRS Letter.doc` under `/google1/Surgery/` moved from
    `letter` to `medical`
  - `Kay Vaginoplasty GRS Letter.doc` under
    `/icloud/untitled folder/sort/combined/Surgery/` moved from `letter` to
    `medical`
  the live runtime then proved a sixth heuristic-learning family:
  - `force_inline_llm_for` now includes `docling-converted|unknown`
  - LightGBM retrained live through `training_rows=676`
  - readiness remained green with:
    - `teacher_reviewed_rows=726`
    - `teacher_approved_rows=677`
    - `feedback_sources.manual-obsidian-note=110`
    - `queue_depth=0`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/untitled folder/B217C1 Buff Parchment.doc`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/Surgery/Kay Vaginoplasty GRS Letter.doc`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/untitled folder/sort/combined/Surgery/Kay Vaginoplasty GRS Letter.doc`
  - resulting notes now land at:
    - `01 Classified/personal/B217C1 Buff Parchment - personal.md`
    - `01 Classified/medical/Kay Vaginoplasty GRS Letter - medical.md`
  - verified frontmatter now shows:
    - `source_parser="docling-converted"`
    - `heuristic_primary_hint="unknown"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `pdftotext|unknown` family:
  - `New Patient Cognitive Questionnaire.pdf` moved from `medical` to `form`
  - `botox.pdf` moved from `medical` to `insurance`
  - `show.pdf` moved from `reimbursement-packet` to `tax-form`
  the live runtime then re-proved the seventh active parser family:
  - `force_inline_llm_for` includes `pdftotext|unknown`
  - fresh strong manual-note rows were exported for all three PDFs
  - LightGBM retrained live to `training_rows=698`
  - readiness remained green with:
    - `teacher_reviewed_rows=747`
    - `teacher_approved_rows=698`
    - `feedback_sources.manual-obsidian-note=120`
    - `queue_depth=0`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/Downloads/New Patient Cognitive Questionnaire.pdf`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/Scanned/botox.pdf`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/Downloads/show.pdf`
  - resulting notes now land at:
    - `01 Classified/form/New Patient Cognitive Questionnaire - form.md`
    - `01 Classified/insurance/botox - insurance.md`
    - `01 Classified/tax-form/show - tax-form.md`
  - verified frontmatter now shows:
    - `source_parser="pdftotext"`
    - `heuristic_primary_hint="unknown"`
    - `hybrid_live_source="manual-correction-override"`
- rerunning the shadow-worker after that live rewrite did not append any newer
  bogus `financial -> financial` manual-note-move row for that receipt source
- `kayraspi` now carries only the legacy cloudsync Postgres database for the
  compute-only cutover; the old service and worker are stopped there
- a pause was requested for the current aggregate background scan so manual
  feedback-learning work can proceed without more crawl churn
- public `clouddrive.neonbutterfly.net/refresh/status` has been flat at
  `items_seen=13000` and `frontier_length=23934` since that pause request
- direct SSH reachability from the workstation to both `kayraspi` and
  `tichuml1` timed out during the pause attempt, so host-level confirmation of
  the worker stop is still pending
- `classification-worker` on `kayraspi` is intentionally stopped after reset
- aggregate mirror indexing has picked up both `google1` and `google2`
- `document-vault` is the canonical local Obsidian vault
- issue [#47](https://github.com/NeonButrfly/iCloudPlugin/issues/47) cleared
  the generated note surfaces in `document-vault` on 2026-05-30 AKDT before
  the next broad ingestion attempt:
  - `01 Classified`
  - `02 Needs Review`
  - `90 Attachments`
  - `_system/classifications`
  - `_system/extracted-markdown`
  - root `Classification Index.md`
- that reset intentionally preserved:
  - `.obsidian`
  - `00 Inbox`
  - `_system/templates`
  - `_system/training`
  - the source mirrors and indexed `files` table
- the smoke classification used
  `/srv/cloud-vault/mirrors/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx`
  and created an `appeal` note in `document-vault`
- `kayraspi2` remains the storage/share/proxy host

## Not Finished Yet

- prove the stronger manual-correction override on more than the single live
  receipt example
- verify the new parser-aware heuristic-learning path on multiple real manual
  corrections so `force_inline_llm_for` picks up at least one meaningful
  parser-plus-hint pattern from user curation (now proven for
  `pdf-ocr-tesseract|unknown`; broader coverage still open)
- the classifier/manual-feedback loop is now live-proven across every current
  parser family present in the vault:
  - `pdf-ocr-tesseract|unknown`
  - `docx-xml|unknown`
  - `plain-text|unknown`
  - `spreadsheet-openpyxl|spreadsheet`
  - `docling|unknown`
  - `docling-converted|unknown`
  - `pdftotext|unknown`
- decide how to backfill richer classifier context for the remaining legacy
  generated notes that still lack `source_parser` / `heuristic_primary_hint` /
  `hybrid_live_source` because their state rows are either still queued or are
  missing entirely
- finish proving the fixed targeted batch helper end to end on the compute-only
  cloudsync host; the original `service "postgres" is not running` failure is
  fixed in repo, but the workstation-timed live helper run still needs one
  clean completion sample
- normalize old hash-heavy note filenames
- retire/archive the old standalone `local-doc-classifier` checkout after safe soak period
- optionally move cloudsync Postgres off `kayraspi` later if the compute-only
  cutover soaks cleanly
- finish an explicit host-level stop of the current background scan once direct
  reachability to `kayraspi` or `tichuml1` recovers
- deploy and validate the new Cloudflare remote MCP slice once Cloudflare
  account auth is available in-session
- decide whether the Worker itself will sit behind Cloudflare Access, another
  OAuth front door, or a different auth product before calling the external MCP
  path production-ready

## Recent Commits That Matter

- `598ff3d50536bbf58e90abc79dc7000f4736a701`
  - `fix: harden classifier api role for live traffic`

- `379e4031c919e78816f5e5be6c3d6fee1156621c`
  - `fix: make classifier image support API role startup`

- `09bcf0e02cf8f66f24dab286e13af40522b65e8b`
  - `feat: support live classifier role cutover`

- `f85d291f69239589c99d4cca1b93d6c5fed3b8af`
  - `docs: consolidate workspace artifacts`

## Best Starting Point For A New Chat

1. Use `C:\Code\iCloudPlugin` as the workspace.
2. Read `docs/workspace-map.md`.
3. Read this file.
4. Treat `/srv/cloud-vault/document-vault` as the canonical Obsidian vault.
5. Assume:
   - `kayraspi2` is storage/share/proxy
   - `tichuml1` is classifier plus live cloudsync compute host
