# Classifier Role

Runs classification, note generation, and vault maintenance on the classifier
 host.

Typical host:

- `tichuml1`

Expected shared mount:

- current live path on `tichuml1`: `/mnt/cloud-vault/local-doc-classifier-vault`
- target future path after vault rename: `/srv/cloud-vault/document-vault`

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
- `CLASSIFIER_API_WORKERS=2` so health and metadata endpoints can still respond
  while a long classification request is running
