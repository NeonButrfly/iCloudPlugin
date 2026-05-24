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
- `deploy/roles/cloudsync/cloud-vault-sync.service`
- `deploy/roles/cloudsync/cloud-vault-sync.timer`

The live storage host currently uses `rclone bisync` for the mirrored cloud
folders:

- `icloud:` <-> `/srv/cloud-vault/mirrors/icloud`
- `gdrive1:` <-> `/srv/cloud-vault/mirrors/google1`
- `gdrive2:` <-> `/srv/cloud-vault/mirrors/google2`

The script is intentionally resilient:

- missing or unauthenticated remotes are skipped instead of failing the whole
  timer run
- the first run seeds bisync state from the local mirror copy
- ongoing runs use a dedicated state directory under
  `/srv/cloud-vault/.rclone-bisync`
