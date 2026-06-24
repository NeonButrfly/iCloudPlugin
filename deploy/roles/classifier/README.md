# Classifier Role

Runs classification, note generation, and vault maintenance on the classifier
 host.

Typical host:

- `tichuml1`

Expected shared mount:

- current live path on `tichuml1`: `/mnt/cloud-vault/document-vault`
- storage-host backing path on `kayraspi2`: `/srv/cloud-vault/document-vault`
- operator-facing SMB path should be a direct vault share such as
  `\\192.168.50.86\document-vault`
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
- `report_codex_arbiter_readiness.sh` for non-secret host-side Codex arbiter
  readiness checks before enabling issue `#20`
- `run_codex_arbiter_smoke.sh` for a one-file authenticated smoke request that
  can force-enable the Codex arbiter per request without changing the service's
  default-off runtime mode

Operational defaults:

- `ENABLE_SHADOW_WORKER=0` to keep the API role focused on request handling
- `CODEX_ARBITER_ENABLED=0` so Codex never participates in classifier
  decisions unless an operator explicitly enables it
- the classifier API can still force-enable Codex for one authenticated smoke
  request via `enable_codex_arbiter_override=true`, which keeps live rollout
  proof for issue `#20` bounded to a single source file instead of flipping the
  whole service into Codex mode
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
- keep `CLASSIFIER_VAULT_DIR=/mnt/cloud-vault/document-vault` on compute
  hosts so generated notes land in the shared vault rather than a host-local
  duplicate under `/srv/cloud-vault/document-vault`
- keep `CLASSIFIER_SOURCE_MOUNT_SOURCE` pointed at the host-visible mirror tree
  and `CLASSIFIER_SOURCE_ROOT` at the in-container mount path (default
  `/source`); the shadow worker now translates canonical mirror paths from
  generated notes back into that mounted source root during manual-feedback
  export
