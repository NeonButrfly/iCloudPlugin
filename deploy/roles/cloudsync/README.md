# Cloudsync Role

Runs mirrored-drive crawl, refresh scheduling, extraction, and reconciliation
 triggers on the sync host.

Typical host:

- `kayraspi2`

Expected shared mount:

- `/srv/cloud-vault`

Primary runtime pieces:

- `apps/cloudsync`
- `apps/api`
- Postgres
