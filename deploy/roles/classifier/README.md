# Classifier Role

Runs classification, note generation, and vault maintenance on the classifier
 host.

Typical host:

- `tichuml1`

Expected shared mount:

- `/srv/cloud-vault/document-vault`

Primary runtime pieces:

- `apps/classifier`
- Ollama

Primary services in `docker-compose.yml`:

- `ollama`
- `model-init`
- `classifier-api`
