# Workspace Map

This repo is the canonical workspace for the cloud-vault platform work.

## Canonical Project

- Repo: `C:\Code\iCloudPlugin`
- Purpose: monorepo for the iCloud connector, sync/index services, classifier role, shared packages, and deployment roles

## Live Host Roles

- `kayraspi` (`192.168.50.232`)
  - transitional legacy `iCloudPlugin` host
  - still hosts the live cloudsync Postgres database during the compute-only cutover
  - repo path: `/opt/iCloudPlugin`

- `tichuml1` (`192.168.50.196`)
  - live classifier host
  - live sync/index/API compute host
  - repo path: `/opt/iCloudPlugin`
  - main service port: `8080`
  - classifier API port: `4319`

- `kayraspi2` (`192.168.50.86`)
  - shared storage, NFS/SMB, proxy, iCloud mirror, iPhone backup host
  - storage root: `/srv/cloud-vault`

- `tichuml` (`192.168.50.36`)
  - Tichu backend/Postgres host
  - not part of the cloud-vault runtime path

## Canonical Artifacts

- architecture discovery bundle:
  - `C:\Code\iCloudPlugin\docs\architecture-discovery\architecture-discovery-20260518-1856-AK`

## Legacy or Transitional Paths

- `C:\Code\local-doc-classifier`
  - legacy standalone repo
  - no longer the target for new platform work
  - keep only until final retirement/archival is complete

- `C:\Users\Keifm\OneDrive\Documents\New project 2`
  - no longer a working project root
  - previous discovery artifacts were moved into this repo

## Canonical Obsidian Vault

- storage-host canonical vault path is `/srv/cloud-vault/document-vault` on
  `kayraspi2`
- compute-host canonical mounted vault path is
  `/mnt/cloud-vault/document-vault` on `tichuml1`
- current operator-facing UNC is `\\192.168.50.86\cloud-vault\document-vault`
- if a direct vault SMB share is added later, it should be
  `\\192.168.50.86\document-vault` and point at that same backing folder
- `/srv/cloud-vault/local-doc-classifier-vault` is a compatibility symlink to
  `document-vault` during the soak period
- `tichuml1:/srv/cloud-vault/document-vault` should not be a separate local
  vault tree; if present, convert it into a compatibility link to the shared
  mounted vault
