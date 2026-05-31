# Cloudsync Role

Runs mirrored-drive crawl, refresh scheduling, extraction, and reconciliation
triggers on the cloudsync compute host.

Preferred host split:

- cloudsync compute host: `tichuml1`
- storage/share host: `kayraspi2`

Expected host-side shared mount on the compute host:

- `/mnt/cloud-vault`

Expected in-container shared mount:

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

For the compute-only deployment on `tichuml1`:

- keep `kayraspi2` authoritative for `/srv/cloud-vault`
- keep the existing cloudsync Postgres on `kayraspi` during the first cutover
- mount `192.168.50.86:/srv/cloud-vault` at `/mnt/cloud-vault` on `tichuml1`
- set `POSTGRES_HOST=192.168.50.232`
- set `POSTGRES_PORT=5432`
- set `ICLOUD_MIRROR_MOUNT_SOURCE=/mnt/cloud-vault`
- leave `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors` so the container path
  stays stable
- keep `CLASSIFIER_API_URL=http://192.168.50.196:4319`
- set `CLASSIFIER_API_TOKEN` to the same live classifier API token used by the
  classifier role; real-folder submission will fail fast if it is blank while
  classification submission is enabled
- when the host is using a remote Postgres instance and you only need to bring
  up `classification-worker`, prefer `docker start icloudplugin-classification-worker-1`
  or `docker compose ... up -d --no-deps classification-worker` so compose does
  not try to recreate the local `postgres` service unnecessarily
- prefer `docker compose -p icloudplugin --env-file deploy/roles/cloudsync/.env.live`
  so the cloudsync project name remains stable during cutover

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
- optionally run in `--targeted-feedback-only` mode so strong manual Obsidian
  corrections can process without seeding broader backfill work
- optionally print newest completed rows across the whole queue with `--run-live-summary`
- optionally write a machine-readable JSON run summary with `--summary-json /path/to/output.json`
- restore deferred jobs automatically on exit
- when the sync host is using the compute-only cutover with remote Postgres,
  the helper now falls back to a disposable `postgres:16` client container
  instead of assuming a local compose `postgres` service exists
