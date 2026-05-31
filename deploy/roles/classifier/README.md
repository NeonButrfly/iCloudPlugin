# Classifier Role

Runs classification, note generation, and vault maintenance on the classifier
 host.

Typical host:

- `tichuml1`

Expected shared mount:

- current live path on `tichuml1`: `/mnt/cloud-vault/document-vault`
- legacy compatibility path on the storage host: `/srv/cloud-vault/local-doc-classifier-vault`

Live migration note:

- use `CLASSIFIER_CONFIG_DIR` to preserve host-local classifier config, models,
  and corrections during cutover from the standalone repo

Primary runtime pieces:

- `apps/classifier`
- Ollama

Primary services in `docker-compose.yml`:

- `ollama`
- `model-init`
- `classifier-api`

Operational defaults:

- `ENABLE_SHADOW_WORKER=0` to keep the API role focused on request handling
- `CODEX_ARBITER_ENABLED=0` so Codex never participates in classifier
  decisions unless an operator explicitly enables it
- `CODEX_ARBITER_COMMAND` defaults to `codex exec`; override it if the live
  host needs extra non-interactive flags or a different Codex binary path
- `CODEX_ARBITER_TIMEOUT_SECONDS=120` bounds a single Codex arbiter attempt so
  a bad external call falls back to the local classifier result instead of
  hanging the request forever
- `CLASSIFIER_API_WORKERS=4` so health and metadata endpoints can still respond
  while concurrent long classification requests are running
- keep `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors` aligned with the
  canonical source paths stored in generated notes, even when the host-mounted
  mirror tree comes from `/mnt/cloud-vault/mirrors`
- keep `CLASSIFIER_SOURCE_MOUNT_SOURCE` pointed at the host-visible mirror tree
  and `CLASSIFIER_SOURCE_ROOT` at the in-container mount path (default
  `/source`); the shadow worker now translates canonical mirror paths from
  generated notes back into that mounted source root during manual-feedback
  export
