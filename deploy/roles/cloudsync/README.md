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
- `deploy/roles/cloudsync/install_storage_host_sync_assets.sh`
- `deploy/roles/cloudsync/run_targeted_classification_batch.sh`
- `deploy/roles/cloudsync/report_live_status.sh`
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
- the refresh worker now also supports operator-tunable mid-batch status
  cadence for image-heavy or OCR-heavy workloads:
  - `ICLOUD_REFRESH_PROGRESS_HEARTBEAT_SECONDS`
  - `ICLOUD_REFRESH_PROGRESS_HEARTBEAT_ITEMS`
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
- storage-host sync can force IPv4 for all `rclone` reachability checks and
  bisync runs with:
  - `RCLONE_FORCE_IPV4=true`
  - this now defaults to `true` because `kayraspi2` can reach iCloud over IPv4
    even when IPv6 egress is unavailable
- ongoing runs use a dedicated state directory under
  `/srv/cloud-vault/.rclone-bisync`
- it now also writes a machine-readable status artifact to:
  - `/srv/cloud-vault/logs/cloud-vault-sync-status.json`
  - the artifact records each remote outcome plus an overall status such as
    `ok` or `degraded`
  - default required/optional remotes:
    - `icloud`: required
    - `gdrive1`: optional
    - `gdrive2`: optional
  - per-remote required flags can be overridden with:
    - `REMOTE_ICLOUD_REQUIRED`
    - `REMOTE_GOOGLE_1_REQUIRED`
    - `REMOTE_GOOGLE_2_REQUIRED`

For bounded classifier backfill work on the sync host, use:

- `deploy/roles/cloudsync/run_targeted_classification_batch.sh`

To install or refresh the storage-host sync assets on `kayraspi2`, use:

- `deploy/roles/cloudsync/install_storage_host_sync_assets.sh`

That helper:

- installs `cloud-vault-sync.sh` to `/usr/local/bin`
- installs the systemd service and timer under `/etc/systemd/system`
- reloads systemd
- enables the timer
- can optionally start one immediate sync pass with `--run-sync-after-install`
- prints source-vs-installed SHA256 hashes for operator verification

For one unified operator status read on the compute host, use:

- `deploy/roles/cloudsync/report_live_status.sh`

That helper prints one JSON report covering:

- cloudsync `/health`
- cloudsync `/refresh/status`
- cloud-vault mirror sync status from `cloud-vault-sync-status.json`
- classifier `/health`
- `classification_jobs` counts
- `classification_states` counts
- indexed provider counts by top-level mirror root
- generated note / attachment / extracted-markdown counts in the shared vault

The refresh-status payload now includes mid-batch timing/liveness fields such as:

- `heartbeat_at`
- `heartbeat_age_seconds`
- `batch_started_at`
- `batch_age_seconds`
- `last_progress_at`
- `progress_age_seconds`
- `batch_stage`
- `current_batch_items_processed`

On long OCR-heavy batches, those fields let operators confirm that the worker
is still advancing even before `batch_count` changes.

It supports the current compute-only cutover with remote Postgres by using the
same direct `postgres:16` client fallback as the targeted batch helper.

If the host account is not in the Docker group, the helper can also use:

- passwordless `sudo`, or
- `SUDO_PASSWORD=...` for a one-shot elevated run

That helper can:

- print before/after queue summaries
- print before/after generated-note classifier-context gap summaries
- temporarily defer one queued path prefix such as `/icloud/Downloads/`
- run a bounded `classification-worker` pass
- optionally run in `--targeted-feedback-only` mode so strong manual Obsidian
  corrections can process without seeding broader backfill work
- optionally run in `--reconciliation-only` mode so one bounded vault
  reconciliation pass can be proven without also advancing the classification
  queue
- optionally override the reconciliation scan limit with
  `--reconciliation-limit N`
- optionally print newest completed rows across the whole queue with `--run-live-summary`
- optionally write a machine-readable JSON run summary with `--summary-json /path/to/output.json`
- restore deferred jobs automatically on exit
- when the sync host is using the compute-only cutover with remote Postgres,
  the helper now falls back to a disposable `postgres:16` client container
  instead of assuming a local compose `postgres` service exists
- if Docker requires elevation on the host, the helper now also supports:
  - passwordless `sudo`, or
  - `SUDO_PASSWORD=...` for a one-shot elevated run
