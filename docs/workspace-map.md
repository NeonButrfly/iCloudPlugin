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

- canonical live vault path is `/srv/cloud-vault/document-vault`
- `tichuml1` mounts it at `/mnt/cloud-vault/document-vault`
- `/srv/cloud-vault/local-doc-classifier-vault` is a compatibility symlink to
  `document-vault` during the soak period
- use `document-vault` for all new Obsidian and classifier configuration
