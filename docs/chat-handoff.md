# Chat Handoff

Canonical workspace is `C:\Code\iCloudPlugin`.

## What This Project Is

- `iCloudPlugin` is the canonical monorepo for the cloud-vault platform.
- It contains the iCloud connector, sync/index/API side, classifier side, shared packages, and deployment roles.
- `C:\Code\local-doc-classifier` is legacy/transitional and is not the source of truth.

## Live Host Layout

- `kayraspi` (`192.168.50.232`)
  - live `iCloudPlugin` sync/API host
  - repo path: `/opt/iCloudPlugin`
  - main service port: `8080`
  - mounts `/srv/cloud-vault` from `kayraspi2` as read-only NFS

- `tichuml1` (`192.168.50.196`)
  - live classifier host
  - repo path: `/opt/iCloudPlugin`
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
- on `kayraspi`, `CLASSIFIER_VAULT_RECONCILIATION_ENABLED=false` is intentional because `/srv/cloud-vault` is mounted read-only there

## Current Status

- `kayraspi` `iCloudPlugin` health is OK
- `kayraspi` `/refresh/status` is running
- `tichuml1` classifier health is OK
- `classification-worker` on `kayraspi` is intentionally stopped after reset
- aggregate mirror indexing has picked up both `google1` and `google2`
- `document-vault` is the canonical local Obsidian vault
- `document-vault` was reset on 2026-05-24 AKDT and contains only the fresh
  classifier smoke output
- classifier training/runtime state was cleared; `/readiness` reports
  `model_exists=false` and `real_ingestion_allowed=false`
- the smoke classification used
  `/srv/cloud-vault/mirrors/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx`
  and created an `appeal` note in `document-vault`
- `kayraspi2` remains the storage/share/proxy host

## Not Finished Yet

- retrain/approve classifier readiness before resuming bulk real-folder submissions
- normalize old hash-heavy note filenames
- retire/archive the old standalone `local-doc-classifier` checkout after safe soak period
- decide whether `cloudsync/api` should remain on `kayraspi` or be intentionally moved later

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
   - `kayraspi` is sync/API
   - `tichuml1` is classifier
