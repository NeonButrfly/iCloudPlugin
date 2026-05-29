# Cloudsync Role

Runs mirrored-drive crawl, refresh scheduling, extraction, and reconciliation
 triggers on the sync host.

Typical host:

- current live app host: `kayraspi`
- current live storage/share host: `kayraspi2`

Expected shared mount:

- `/srv/cloud-vault`

Primary runtime pieces:

- `apps/cloudsync`
- `apps/api`
- `classification-worker`
- Postgres

Primary services in `docker-compose.yml`:

- `postgres`
- `migrate`
- `service`
- `worker`
- `classification-worker`

Related host-level sync assets:

- `deploy/roles/cloudsync/cloud-vault-sync.sh`
- `deploy/roles/cloudsync/run_targeted_classification_batch.sh`
- `deploy/roles/cloudsync/cloud-vault-sync.service`
- `deploy/roles/cloudsync/cloud-vault-sync.timer`

The live storage host currently uses `rclone bisync` for the mirrored cloud
folders:

- `icloud:` <-> `/srv/cloud-vault/mirrors/icloud`
- `gdrive1:` <-> `/srv/cloud-vault/mirrors/google1`
- `gdrive2:` <-> `/srv/cloud-vault/mirrors/google2`

The sync/index/classifier-facing mirror root should point at:

- `/srv/cloud-vault/mirrors`

That keeps one local source of truth for indexing and classifier submission
while still preserving provider-specific provenance by folder.

The script is intentionally resilient:

- missing or unauthenticated remotes are skipped instead of failing the whole
  timer run
- the first iCloud run seeds bisync state from the existing local mirror copy
- the first Google Drive runs seed bisync state from the remote Drive accounts
  so an empty local mirror cannot become the initial source of truth
- dangling Google Drive shortcuts are skipped because rclone cannot read them
  as source objects
- ongoing runs use a dedicated state directory under
  `/srv/cloud-vault/.rclone-bisync`

For bounded classifier backfill work on the sync host, use:

- `deploy/roles/cloudsync/run_targeted_classification_batch.sh`

That helper can:

- print before/after queue summaries
- temporarily defer one queued path prefix such as `/icloud/Downloads/`
- run a bounded `classification-worker` pass
- optionally print newest completed rows across the whole queue with `--run-live-summary`
- restore deferred jobs automatically on exit
