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
- `CLASSIFIER_API_WORKERS=4` so health and metadata endpoints can still respond
  while concurrent long classification requests are running
