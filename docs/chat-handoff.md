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
- `tichuml1` `/refresh/status` resumed the existing aggregate background scan
- `clouddrive.neonbutterfly.net` now proxies to `192.168.50.196:8080`
- `tichuml1` classifier health is OK
- `tichuml1` classifier containers were recreated from the monorepo compose on
  2026-05-29 AKDT while preserving the existing trained runtime/output
  directories under `/opt/local-doc-classifier` for continuity
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
- the shadow worker now syncs manual note feedback before running its
  retrain/update pass, and manual-feedback rows with real parser context can
  now contribute to `force_inline_llm_for` heuristic gating updates
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
- `document-vault` now contains both the original smoke output and additional
  live classifier notes from the resumed pipeline work
- the smoke classification used
  `/srv/cloud-vault/mirrors/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx`
  and created an `appeal` note in `document-vault`
- `kayraspi2` remains the storage/share/proxy host

## Not Finished Yet

- prove the stronger manual-correction override on more than the single live
  receipt example
- verify the new parser-aware heuristic-learning path on multiple real manual
  corrections so `force_inline_llm_for` picks up at least one meaningful
  parser-plus-hint pattern from user curation
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
