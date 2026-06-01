# Chat Handoff

Canonical workspace is `C:\Code\iCloudPlugin`.

## What This Project Is

- `iCloudPlugin` is the canonical monorepo for the cloud-vault platform.
- It contains the iCloud connector, sync/index/API side, classifier side, shared packages, and deployment roles.
- `C:\Code\local-doc-classifier` is legacy/transitional and is not the source of truth.

## Live Host Layout

- `kayraspi` (`192.168.50.232`)
  - transitional legacy `iCloudPlugin` host
  - still hosts the live cloudsync Postgres database during the compute-only cutover
  - repo path: `/opt/iCloudPlugin`
  - mounts `/srv/cloud-vault` from `kayraspi2` as read-only NFS

- `tichuml1` (`192.168.50.196`)
  - live classifier host
  - live sync/index/API compute host
  - repo path: `/opt/iCloudPlugin`
  - main service port: `8080`
  - classifier API port: `4319`
  - mounts shared vault from `kayraspi2` at `/mnt/cloud-vault`

- `kayraspi2` (`192.168.50.86`)
  - storage/share/proxy host
  - local storage root: `/srv/cloud-vault`
  - runs NFS, SMB, Caddy, iCloud mirror sync, and iPhone backup timers

- `tichuml` (`192.168.50.36`)
  - Tichu backend/Postgres host
  - not part of the cloud-vault runtime path

## Important Paths

- canonical repo:
  - `C:\Code\iCloudPlugin`

- workspace map:
  - `C:\Code\iCloudPlugin\docs\workspace-map.md`

- architecture discovery bundle:
  - `C:\Code\iCloudPlugin\docs\architecture-discovery\architecture-discovery-20260518-1856-AK`

- canonical live vault path:
  - `/srv/cloud-vault/document-vault`

- legacy compatibility vault path:
  - `/srv/cloud-vault/local-doc-classifier-vault` -> `document-vault`

## What Was Completed

- shared SSH key access was installed for all four hosts
- `tichuml1` classifier service was cut over to the monorepo deployment from `/opt/iCloudPlugin`
- `kayraspi` `/opt/iCloudPlugin` was updated to current `main` and rebuilt
- the old `New project 2` architecture artifacts were moved into repo docs
- the repo now has a canonical workspace map and consolidated artifact location
- the reconciliation path now normalizes legacy hash-heavy generated note
  filenames back to clean human-readable names and rewrites stored note
  references accordingly
- the repo now also has the first real Codex final-arbiter implementation path:
  - still disabled by default behind `CODEX_ARBITER_ENABLED=0`
  - bounded by `CODEX_ARBITER_TIMEOUT_SECONDS`
  - driven by `CODEX_ARBITER_COMMAND` (default `codex exec`)
  - falls back to the local classifier result on invalid JSON, timeout, or CLI
    execution failure instead of breaking note generation
  - classifier `/health` now exposes a non-secret `codex_arbiter` readiness
    block
  - `deploy/roles/classifier/report_codex_arbiter_readiness.sh` now provides
    the same host-side readiness view without printing secrets
  - `deploy/roles/classifier/run_codex_arbiter_smoke.sh` can now run one
    authenticated `/classify/source` smoke request and force-enable the Codex
    arbiter for just that request, so issue `#20` can be proven on-host without
    flipping the whole classifier service into Codex mode
  - a local dry run on 2026-05-31 AKDT proved:
    - Codex CLI discoverable from the current machine
    - auth present via `~/.codex/auth.json`
    - classifier health follow-up remains blocked until a real
      `CLASSIFIER_API_TOKEN` is loaded

## Important Deployment Fixes Already Made

- the classifier image was fixed to include the shared `packages/` tree
- the classifier image was fixed to use `CMD` instead of `ENTRYPOINT` so API startup override works
- the classifier API role was hardened for live traffic:
  - `ENABLE_SHADOW_WORKER=0` by default in the API role
  - four Uvicorn workers in the classifier API role
- on `kayraspi`, `CLASSIFIER_VAULT_RECONCILIATION_ENABLED=false` is intentional when that host is using the read-only NFS mount from `kayraspi2`

## Current Status

- `tichuml1` `iCloudPlugin` health is OK on `127.0.0.1:8080`
- `tichuml1` `/refresh/status` is still running the active aggregate
  background scan
- live `/refresh/status` on 2026-05-30 AKDT shows:
  - `status=running`
  - `job_id=12`
  - `job_type=metadata-refresh`
  - `source=background-scan`
  - `items_seen=1700`
  - `batch_count=17`
  - `frontier_length=2218`
  - `error_message=null`
- issue [#4](https://github.com/NeonButrfly/iCloudPlugin/issues/4) is now
  fixed live on `tichuml1`:
  - `/refresh/status` now exposes batch-liveness and timing fields including:
    - `heartbeat_at`
    - `heartbeat_age_seconds`
    - `batch_started_at`
    - `batch_age_seconds`
    - `last_progress_at`
    - `progress_age_seconds`
    - `batch_stage`
    - `current_batch_size`
    - `current_batch_items_processed`
    - `current_batch_items_remaining`
  - the refresh worker now persists mid-batch progress during extraction-heavy
    work instead of waiting for the full batch boundary
  - live proof on 2026-05-31 AKDT after worker recovery showed one running
    batch with:
    - `batch_count=377`
    - `items_seen=37700 -> 37701 -> 37719 -> 37768`
    - `current_batch_items_processed=0 -> 1 -> 19 -> 68`
    - `batch_stage=extracting`
    while the batch stayed in flight
  - the live API and refresh worker on `tichuml1` are currently being served by
    the role-based cloudsync compose path:
    - `cloudsync-service-1`
    - `cloudsync-worker-1`
- issue [#2](https://github.com/NeonButrfly/iCloudPlugin/issues/2) is now
  fixed and ready to close:
  - resumable background indexing is live
  - restart recovery is live
  - the root reindex helpers now match the role-based cloudsync deployment and
    current auth model:
    - `scripts/reindex-icloud-index.sh`
    - `scripts/reindex-icloud-index.ps1`
  - both helpers now:
    - default to `deploy/roles/cloudsync/.env.live`
    - default to `deploy/roles/cloudsync/docker-compose.yml`
    - require explicit destructive confirmation
    - support dry-run planning
    - understand remote-Postgres compute-only deployments
    - truncate `classification_jobs`, `classification_states`,
      `extracted_contents`, `files`, `jobs`, and `sync_runs`
    - queue a fresh refresh run with bearer auth when `PLUGIN_API_TOKEN` is set
  - safe live proof on `tichuml1` on 2026-05-31 AKDT:
    - `bash ./scripts/reindex-icloud-index.sh --dry-run --yes`
      selected the remote-Postgres compute-only path
    - the planned refresh POST showed a redacted bearer header instead of
      leaking the live token
- issue [#6](https://github.com/NeonButrfly/iCloudPlugin/issues/6) is also now
  closure-ready:
  - `create_icloud_web_client()` already supports
    `ICLOUD_SOURCE_MODE=filesystem-mirror`
  - the role-based cloudsync and combined compose files already default to:
    - `ICLOUD_SOURCE_MODE=filesystem-mirror`
    - `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors`
  - mirror-backed traversal and source selection are covered by:
    - `tests/test_icloud_web_client.py`
    - `tests/test_health_api.py`
    - `tests/test_auth_session_manager.py`
    - `tests/test_classification_submission.py`
  - live proof on 2026-05-31 AKDT from authenticated `GET /status/summary`:
    - `auth_status.status=configured`
    - `provider_counts={icloud:37866, google1:1991, google2:1409}`
    - refresh is actively crawling while the runtime is in
      filesystem-mirror mode
- issue [#7](https://github.com/NeonButrfly/iCloudPlugin/issues/7) is now also
  closure-ready:
  - durable `classification_jobs` and `classification_states` already exist and
    are actively used by `classification-worker`
  - backfill plus ongoing submission are already live in parallel with refresh
  - priority buckets and fingerprint-based skip logic are already covered by
    `tests/test_classification_submission.py`
  - live proof on 2026-05-31 AKDT from authenticated `GET /status/summary`:
    - `classification_job_counts={completed:97, failed:2, queued:84, running:1}`
    - `classification_state_counts={completed:65, queued:85}`
    - refresh remained active at the same time
- issue [#22](https://github.com/NeonButrfly/iCloudPlugin/issues/22) is now
  closure-ready too:
  - the repo already has a shared canonical label map in
    `apps/classifier/label_map.py`
  - canonicalization is already used by:
    - index-driven LightGBM training
    - hybrid gating
    - reviewed example ingestion
  - live proof on 2026-05-31 AKDT from classifier `/readiness`:
    - `teacher_reviewed_rows=1032`
    - `teacher_approved_rows=963`
    - `teacher_live_agreement_rows=944`
    - `teacher_approval_rate=0.93314`
    - `teacher_agreement_rate=0.98027`
    - `real_ingestion_allowed=true`
- `clouddrive.neonbutterfly.net` now proxies to `192.168.50.196:8080`
- `tichuml1` classifier health is OK
- `tichuml1` classifier containers were recreated from the monorepo compose on
  2026-05-29 AKDT while preserving the existing trained runtime/output
  directories under `/opt/local-doc-classifier` for continuity
- the repo now contains the first Cloudflare remote MCP slice under
  `cloudflare/remote-mcp` from issue
  [#48](https://github.com/NeonButrfly/iCloudPlugin/issues/48)
  - the on-prem service now has plugin-token-protected file/note/source routes:
    - `GET /files/{id}`
    - `GET /files/{id}/note`
    - `GET /files/{id}/source`
    - `GET /files/{id}/source/download`
  - the repo-local MCP bridge now exposes:
    - `search_icloud_notes_and_files`
    - `get_icloud_system_status`
    - `get_icloud_product_readiness`
    - `get_icloud_note`
    - `get_icloud_source_reference`
    - `get_icloud_file_bundle`
  - the combined search tool now searches once and hydrates the top matches
    into bundled file/note/source payloads so external ChatGPT callers do not
    need to stitch multiple follow-up calls together for common analysis flows
  - that combined retrieval path is now also first-class on the origin service
    through `GET /search/bundles`, so both the local bridge and the Cloudflare
    Worker reuse the same bundle assembly path
  - the repo now also has a first-class consolidated status surface for MCP
    callers through:
    - origin `GET /status/summary`
    - local MCP `get_icloud_system_status`
    - Cloudflare Worker `get_icloud_system_status`
  - the repo now also has a first-class product-readiness surface through:
    - origin `GET /status/readiness`
    - local MCP `get_icloud_product_readiness`
    - Cloudflare Worker `get_icloud_product_readiness`
  - that readiness payload wraps:
    - `status_summary`
    - repo-surface facts about MCP/deploy/helper coverage
    - explicit end-to-end criteria marked `met`, `blocked`, or `unknown`
  - the origin summary payload now includes:
    - service health
    - auth status
    - refresh progress
    - mirror sync status
    - classifier health
    - `classification_jobs` counts
    - `classification_states` counts
    - provider counts
    - generated vault output counts
    - generated-note classifier-context gap counts for legacy notes that still
      lack `source_parser` / `heuristic_primary_hint` / `hybrid_live_source`
  - the storage-host sync script now writes one machine-readable status
    artifact per run at:
    - `/srv/cloud-vault/logs/cloud-vault-sync-status.json`
    - default required/optional remotes:
      - `icloud`: required
      - `gdrive1`: optional
      - `gdrive2`: optional
    - the artifact records per-remote outcomes plus an overall status such as
      `ok` or `degraded`
  - issue [#13](https://github.com/NeonButrfly/iCloudPlugin/issues/13) is now
    fixed and closed with live proof:
    - `/usr/local/bin/cloud-vault-sync.sh` on `kayraspi2` now writes
      `/srv/cloud-vault/logs/cloud-vault-sync-status.json`
    - the current live artifact records:
      - `overall_status=ok`
      - `required_failures_present=false`
      - per-remote rows for `icloud`, `gdrive1`, and `gdrive2`
    - `deploy/roles/cloudsync/report_live_status.sh` on `tichuml1` now
      includes `cloud_vault_sync`
    - authenticated `GET /status/summary` on `tichuml1` now also includes
      `cloud_vault_sync`
  - the repo still needed a canonical storage-host installer path for those
    sync assets, so issue [#51](https://github.com/NeonButrfly/iCloudPlugin/issues/51)
    is now fixed and closed with live proof:
    - `deploy/roles/cloudsync/install_storage_host_sync_assets.sh` now
      installs or refreshes:
      - `/usr/local/bin/cloud-vault-sync.sh`
      - `/etc/systemd/system/cloud-vault-sync.service`
      - `/etc/systemd/system/cloud-vault-sync.timer`
    - live proof on `kayraspi2` used the role asset bundle from `/tmp` because
      that host does not currently keep a repo checkout at `/opt/iCloudPlugin`
    - installed SHA256 hashes matched the repo assets exactly
    - `cloud-vault-sync.timer` remained `enabled` and `active` after install
  - the Cloudflare Worker scaffold proxies those same surfaces and can hand off
    original files through `/download/{file_id}`
  - it now also proxies `/status/readiness`, so hosted MCP callers can inspect
    the current end-to-end completion state through the same external surface
  - the Worker now also supports an optional client-facing bearer gate via
    `WORKER_API_TOKEN` and exposes non-secret health metadata at `/` and
    `/healthz` for deployment verification
  - both the repo-local MCP bridge and the Cloudflare Worker now also expose
    explicit MCP tool annotations plus `outputSchema` on every tool descriptor
    so the external ChatGPT/App-review surface is less implicit:
    - read tools set:
      - `readOnlyHint=true`
      - `openWorldHint=false`
      - `destructiveHint=false`
    - `refresh_icloud_index` sets:
      - `readOnlyHint=false`
      - `openWorldHint=false`
      - `destructiveHint=false`
  - repo-local operator helpers now exist in `cloudflare/remote-mcp/scripts`:
    - `deploy-and-verify.mjs` plans/deploys/verifies the Worker without relying
      on remembered Wrangler flags
      - it can now also push Worker secrets from shell env or a local
        `.dev.vars`-style file before deploy
    - `verify-mcp-tools.mjs` now smoke-tests the remote `/mcp` route itself by
      connecting over Streamable HTTP, listing tools, and calling one probe
      tool instead of stopping at `/healthz`
      - it also now supports custom headers and Cloudflare Access env fallbacks
        so the same smoke path can verify an Access-fronted Worker, not just
        the temporary Worker bearer token gate
      - the default probe tool is now `get_icloud_product_readiness`, so the
        smoke path checks end-to-end completion state instead of only raw
        runtime status
    - `deploy-and-verify.mjs` now chains that `/mcp` smoke step after deploy by
      default instead of stopping at `/healthz`
    - `.github/workflows/remote-mcp-deploy.yml` now provides a manual
      GitHub-hosted path for:
      - `deploy-and-verify`
      - `mcp-verify-only`
      - `plan`
      using repo secrets instead of workstation-local Cloudflare auth
      - `cloudflare/remote-mcp/scripts/bootstrap-github-secrets.mjs` now
        provides the matching GitHub secret/variable bootstrap path from local
        `.env`-style values
        - required mappings:
          - `CLOUDFLARE_API_TOKEN`
          - `ORIGIN_BASE_URL -> REMOTE_MCP_ORIGIN_BASE_URL`
          - `ORIGIN_API_TOKEN -> REMOTE_MCP_ORIGIN_API_TOKEN`
        - `REMOTE_MCP_PUBLIC_BASE_URL` is written as a repo variable and the
          workflow now reads it from `vars.REMOTE_MCP_PUBLIC_BASE_URL`
      - first external proof on 2026-05-31 AKDT:
        - safe `plan` run succeeded:
          - `https://github.com/NeonButrfly/iCloudPlugin/actions/runs/26725919393`
        - real `deploy-and-verify` run failed fast at secrets preflight:
          - `https://github.com/NeonButrfly/iCloudPlugin/actions/runs/26725879668`
          - missing required GitHub Actions secrets:
            - `CLOUDFLARE_API_TOKEN`
            - `REMOTE_MCP_ORIGIN_BASE_URL`
            - `REMOTE_MCP_ORIGIN_API_TOKEN`
        - partial secret bootstrap follow-up on 2026-05-31 AKDT:
          - repo secret `REMOTE_MCP_ORIGIN_BASE_URL` is now populated with the
            live public origin base URL `https://clouddrive.neonbutterfly.net`
          - rerun `deploy-and-verify` proof:
            - `https://github.com/NeonButrfly/iCloudPlugin/actions/runs/26726168346`
          - preflight now shows `ORIGIN_BASE_URL` present and only these values
            still missing:
            - `CLOUDFLARE_API_TOKEN`
            - `REMOTE_MCP_ORIGIN_API_TOKEN`
      - the workflow now uses `actions/checkout@v6` and `actions/setup-node@v6`
        to avoid the Node 20 GitHub Actions runtime deprecation warning seen in
        the first plan/deploy attempts
    - the Worker runtime no longer depends on Cloudflare's broader `agents`
      package for MCP request handling; it now uses an in-repo stateless
      handler built directly on the MCP SDK's Web Standard Streamable HTTP
      transport
    - local end-to-end proof now exists in
      `cloudflare/remote-mcp/tests/mcp-e2e.test.ts`
      - real MCP client -> Worker route
      - `tools/list`
      - explicit annotations/outputSchema visible on the descriptors
      - `get_icloud_product_readiness`
      - bundled-search `worker_download_url` rewriting
    - `cloudflare/remote-mcp/chatgpt-app-submission.json` now captures the
      current ChatGPT Apps submission-facing view of the hosted MCP surface so
      app metadata, tool names, and review test cases are not left implicit
      - `scripts/generate-chatgpt-app-submission.mjs` now verifies or rewrites
        that artifact from structured source data instead of leaving it purely
        hand-maintained
      - `submission:verify` now also checks the generated metadata against the
        actual Worker-exposed tool surface, not just the checked-in JSON file
      - repo-side Python tests now also compare the same submission artifact
        against the local FastMCP bridge, so the shared tool contract is
        enforced on both MCP surfaces
      - direct `GET /mcp` now returns `405 Allow: POST, DELETE` so
        streamable-http clients do not hang on a standalone SSE path
    - `print-access-bootstrap.mjs` emits ready-to-run Cloudflare Access
      bootstrap commands for the recommended self-hosted Access model
    - `.dev.vars.example` documents the local Worker secret shape for
      `wrangler dev`
    - `dev-and-verify.mjs` now provides the missing local deploy-shaped smoke
      path before Cloudflare account auth exists:
      - starts `wrangler dev` with a temporary env file
      - waits for `/healthz`
      - verifies `/mcp` with the real MCP smoke client
      - bounds the MCP verification time so hangs fail fast
      - cleans up local `workerd` processes on Windows after the run
  - the Worker now also has local Vitest coverage for:
    - worker-token auth gating
    - `/healthz` and `/` health responses
    - origin bearer-auth propagation
    - download proxying
    - worker download URL enrichment
    - digest-compare fallback when `crypto.subtle.timingSafeEqual` is absent
  - the new status-summary slice is now deployed live on `tichuml1`:
    - origin `GET /status/summary` is live
    - local MCP `get_icloud_system_status` points at it
    - Cloudflare Worker `get_icloud_system_status` is wired to it in repo
  - local validation for that slice passed:
    - Python API/client tests passed locally
    - Worker type-check passed locally
    - Worker Vitest suite still passed locally
  - live proof on 2026-05-31 AKDT:
    - authenticated `GET /status/summary` returned:
      - `service_health.status=ok`
      - `auth_status.status=configured`
      - `refresh_status.status=running`
      - `refresh_status.items_seen=27400`
      - `refresh_status.frontier_length=11953`
      - `classifier_health.ok=true`
      - `classification_job_counts={completed:49, failed:2, queued:36, running:1}`
      - `provider_counts={icloud:37866, google1:1991, google2:1409}`
      - `vault_counts={classified_files:9, needs_review_files:6, attachments_files:0, extracted_markdown_files:15}`
    - the service role also now needs `CLASSIFIER_API_URL` and
      `CLASSIFIER_API_TOKEN` in its env so that summary route can report live
      classifier health
  - follow-up issue [#50](https://github.com/NeonButrfly/iCloudPlugin/issues/50)
    is now implemented, verified live, and closed:
    - `deploy/roles/cloudsync/report_live_status.sh` prints one unified live
      status report covering:
      - service health
      - refresh progress
      - classifier health
      - `classification_jobs` counts
      - `classification_states` counts
      - provider counts
      - vault output counts
    - the helper was re-proven on `tichuml1` with the current compute-only
      shape:
      - remote Postgres on `192.168.50.232`
      - shared vault mounted at `/mnt/cloud-vault/document-vault`
      - elevated Docker access via `SUDO_PASSWORD`
    - live proof on 2026-05-31 AKDT showed:
      - service health `ok`
      - refresh status still `running`
      - classifier health `ok`
      - provider counts:
        - `icloud=37866`
        - `google1=1991`
        - `google2=1409`
      - vault counts:
      - `classified_files=6`
      - `needs_review_files=5`
      - `attachments_files=0`
  - follow-up issue [#46](https://github.com/NeonButrfly/iCloudPlugin/issues/46)
    is now fixed in repo and reproven live on `tichuml1`:
    - `run_targeted_classification_batch.sh` now supports the same elevated
      Docker access paths as `report_live_status.sh`:
      - direct Docker-group access
      - passwordless `sudo`
      - `SUDO_PASSWORD=...` for one-shot elevated runs
    - the bounded worker pass now runs through that wrapper instead of
      assuming plain `docker compose`
    - live proof on 2026-05-31 AKDT used:
      - `ENV_FILE=/opt/iCloudPlugin/deploy/roles/cloudsync/.env.live`
      - `SUDO_PASSWORD=kay`
      - `--targeted-feedback-only --max-polls 1 --concurrency 1`
      - `--worker-timeout 180`
      - `--summary-json /tmp/targeted-helper-summary.json`
    - result:
      - helper completed successfully on the compute-only host
      - `worker_exit_status=0`
      - `worker_timed_out=false`
      - `classification_states.completed` moved `44 -> 46`
      - `classification_states.queued` moved `66 -> 68`
      - fresh completed rows included:
        - `/icloud/Scanned/Cars/02212025_Hot-Swappable Tri-Mode RGB BOYI IK87 Mechanical Keyboar.pdf`
        - `/icloud/Scanned/Cars/02212025_APPOLLO.pdf`
  - this slice was validated locally with Python tests plus Worker TypeScript
    type-check
  - the on-prem origin half of the slice is now deployed live on `tichuml1`
    as of 2026-05-31 AKDT:
    - `/search`, `POST /refresh`, and `/files/*` enforce bearer auth
    - `GET /files/{id}/note` is live
    - `GET /files/{id}/source` is live
    - `GET /files/{id}/source/download` is live
    - live sample file `23` proved canonical source metadata and UNC
      `source_link` output; `note_available` was correctly `false` because the
      generated vault surfaces had been cleared before fresh ingestion
  - Cloudflare account-side deployment is still **not** validated because:
    - `npx wrangler whoami` reports `Not logged in`
    - non-interactive Cloudflare deploy/list flows require
      `CLOUDFLARE_API_TOKEN`
  - `scripts/report_product_readiness.py` now provides one canonical repo-plus-
    runtime audit surface for the still-open end-to-end criteria:
    - it inspects the repo for the MCP bridge, Worker, deploy helpers,
      submission artifact, Codex arbiter helpers, and reconciliation helper
    - it can consume either:
      - live authenticated `GET /status/summary`
      - or a saved `report_live_status.sh --summary-json ...` artifact
    - without `CLOUDFLARE_API_TOKEN`, it keeps the auth/deploy criterion
      explicitly blocked instead of implying the external Worker path is
      complete
    - this turn re-proved that the local auth surfaces are still absent:
      - `CLOUDFLARE_API_TOKEN=missing`
      - `npx wrangler deployments list` still fails in non-interactive mode
  - the deploy helper is stronger now despite that blocker:
    - `--sync-secrets` can push Worker secrets before deploy
    - `--secrets-file .dev.vars` lets the helper consume the same local secret
      file used by `wrangler dev`
  - follow-up bug [#49](https://github.com/NeonButrfly/iCloudPlugin/issues/49)
    is now fixed in repo, repaired live on `tichuml1`, and closed:
    - the live cloudsync env had `CLASSIFIER_API_TOKEN` blank, which broke
      real-folder classifier submission with classifier API `401`
    - the token is now synced from the classifier role env
    - the cloudsync `classification-worker` is running again
    - fresh smoke file `8213`
      (`/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx`) completed
      successfully and regenerated:
      - `01 Classified/medical/appeals/Aetna Life Insurance Company - APPEAL 1 FFS - medical - appeals.md`
      - `attachment_mode=canonical-source-link`
      - UNC `source_link` back to `\\192.168.50.86\cloud-vault\mirrors\google1\...`
      - `/files/8213/note` now returns `note_available=true`
      - `90 Attachments` stayed at `0` files during the smoke proof
- live classifier readiness recovered and is green again:
  - `model_exists=true`
  - `real_ingestion_allowed=true`
  - `teacher_reviewed_rows=569`
  - `teacher_approved_rows=546`
  - `feedback_sources.manual-obsidian-note=22`
- a one-shot `shadow-worker` run on 2026-05-29 AKDT scanned `39` vault notes,
  exported `1` fresh manual-feedback row from a real note move, and retrained
  LightGBM live with `training_rows=545`
- the live manual-feedback artifact now includes the receipt correction for
  `/srv/cloud-vault/mirrors/icloud/Scanned/03182023_You for Shopping at Lowe’s your new purchase!.pdf`
  with `correct_label=receipt` and `old_label=financial`
- a direct bounded cloudsync classification-worker run created and completed
  targeted job `#55` for that same receipt source file
- the classifier now honors strong reviewed corrections by canonical source path
  and ignores no-op generated-note feedback rows where `correct_label` matches
  `old_label`
- after the follow-up live redeploy on 2026-05-29 AKDT, the same receipt source
  now rewrites correctly to:
  `01 Classified/receipt/03182023_You for Shopping at Lowe’s your new purchase! - receipt.md`
  with `primary_label="receipt"` and `confidence=1.0`
- generated notes now also persist `source_parser` and `hybrid_live_source`
  frontmatter for future manual-feedback export; a live receipt reclassification
  on 2026-05-29 AKDT confirmed:
  - `source_parser="pdf-ocr-tesseract"`
  - `hybrid_live_source="manual-correction-override"`
- `fix: ignore stale no-op bootstrap feedback` was deployed live on
  2026-05-29 AKDT, and a forced LightGBM retrain then rebuilt the model from
  the cleaned teacher set:
  - `teacher_reviewed_rows=565`
  - `teacher_approved_rows=540`
  - `feedback_sources.manual-obsidian-note=4`
  - `feedback_sources.reviewed-example=500`
  - `feedback_sources.shadow-qwen=36`
  - LightGBM `training_rows=540`
  - LightGBM `class_count=18`
  - LightGBM `trained_at=2026-05-30T05:58:03Z`
- the shadow worker now syncs manual note feedback before running its
  retrain/update pass, and manual-feedback rows with real parser context can
  now contribute to `force_inline_llm_for` heuristic gating updates
- the bounded vault reconciliation pass now also backfills missing
  `source_parser`, `heuristic_primary_hint`, and `hybrid_live_source`
  frontmatter in older generated notes from stored classification-state
  payloads, so pre-existing manual note moves can export richer training
  signals without recreating the note first
- if those note fields are still missing and there is no surviving
  `classification_state` payload to recover from, the same reconciliation path
  now derives the missing context from the live source file itself and
  backfills only the missing fields instead of leaving the note context-poor
- `deploy/roles/cloudsync/run_targeted_classification_batch.sh` can now also
  run a bounded `--reconciliation-only` proof pass and capture before/after
  generated-note context-gap summaries plus the direct reconciliation result in
  one JSON artifact, which is the intended live-proof path for issue `#52`
- live proof on 2026-05-31 AKDT now confirms the intended host split for
  issue `#52`:
  - `kayraspi` is **not** the right proof host for reconciliation repair
    because its cloud-vault mount is read-only; a bounded reconciliation pass
    there failed when note repair tried to write back into
    `/srv/cloud-vault/document-vault`
  - `tichuml1` **is** the right proof host because it has the writable shared
    vault mount and can still reach the remote Postgres on `kayraspi`
  - using a temporary current-checkout proof run on `tichuml1` with
    `--reconciliation-limit 25`:
    - the first bounded pass reported
      `{"ambiguous":0,"repaired":11,"scanned":25,"skipped":5,"unverified":0}`
    - an immediate second pass reported
      `{"ambiguous":0,"repaired":0,"scanned":25,"skipped":5,"unverified":0}`
    - stable post-repair note-context summary:
      - `total_generated_notes=139`
      - `notes_missing_any_context=0`
      - `missing_context_with_matching_completed_state=0`
      - `missing_context_without_matching_state=0`
      - `missing_context_source_file_present=0`
  - spot checks on freshly touched notes under `/mnt/cloud-vault/document-vault`
    now show populated:
    - `source_parser`
    - `heuristic_primary_hint`
    - `hybrid_live_source`
- a bounded live reconciliation pass on 2026-05-29 AKDT repaired `24` out of
  `25` completed-state notes scanned and reduced generated notes missing that
  newer classifier-context frontmatter from `42` to `19`
  - the remaining `19` split cleanly into:
    - `7` notes whose matching `classification_state` rows are still `queued`
    - `12` notes with no surviving `classification_state` row to recover from
- after `feat: derive legacy feedback context from source files`, a live
  `shadow-worker` smoke run on 2026-05-29 AKDT also proved that a moved legacy
  generated note with no stored classifier context now exports derived
  `parser` and `heuristic_primary` values directly from the source file itself
  (`plain-text` + `legal` in the smoke case) instead of falling back to
  `obsidian-generated-note`
- after `fix: retrain from fresh manual feedback`, a live `shadow-worker` pass
  on 2026-05-29 AKDT retrained LightGBM immediately from `2` fresh manual
  teacher rows even though the broader corpus growth was still below the old
  `min_new_rows_since_last_train` gate
  - resulting live retrain report:
    - `retrained=true`
    - `training_rows=542`
    - `new_teacher_rows=2`
    - `new_manual_teacher_rows=2`
    - `trained_at=2026-05-30T06:35:42Z`
  - live heuristic rules still did **not** expand beyond
    `pdftotext|unknown`; current manual-note feedback artifact only contains
    one effective strong generated-note move pair, so the heuristic-update
    path is now code-ready but still signal-limited in live data
- after four additional real generated-note moves on 2026-05-29 AKDT in the
  `pdf-ocr-tesseract|unknown` family, the live `shadow-worker` finally proved
  the heuristic-learning path end to end:
  - strong manual-note rows grew from `1` to `5`
  - LightGBM retrained again from `542` to `546` approved teacher rows
  - live heuristic rules now include:
    - `pdftotext|unknown`
    - `pdf-ocr-tesseract|unknown`
  - readiness remained green with:
    - `teacher_reviewed_rows=571`
    - `teacher_approved_rows=546`
    - `feedback_sources.manual-obsidian-note=10`
    - `real_ingestion_allowed=true`
- after `fix: translate canonical feedback sources into classifier mount`, the
  live classifier role on `tichuml1` now also preserves parser recovery for
  canonical mirror paths that are only host-visible through the shared source
  mount:
  - `ICLOUD_MIRROR_ROOT=/srv/cloud-vault/mirrors` is now passed into the
    classifier API and shadow-worker roles alongside `CLASSIFIER_SOURCE_ROOT`
  - a live probe inside `cloud-vault-classifier-shadow-worker` on
    2026-05-29 AKDT confirmed both
    `/srv/cloud-vault/mirrors/google1/Codex-Multi-Drive-Probe/google-drive-submission-test.txt`
    and
    `/mnt/cloud-vault/mirrors/google1/Codex-Multi-Drive-Probe/google-drive-submission-test.txt`
    now resolve to the mounted source tree and return:
    - `parser="plain-text"`
    - `heuristic_primary="unknown"`
    - `hybrid_live_source=""`
  - before that fix, the same helper path was falling back to
    `parser="obsidian-generated-note"` for those legacy-style canonical paths
- after three real manual moves on 2026-05-29 AKDT in the `docx-xml|unknown`
  family:
  - `Appeal.docx` -> `02 Needs Review/appeal/...`
  - `2024-08-27 Kay Myers Internal Appeal Draft.docx` -> `02 Needs Review/appeal/...`
  - `2023.GAS.Appeal.Template.and.Instructions.Final.docx` ->
    `02 Needs Review/appeal-template/...`
  the live manual-feedback artifact gained three new strong manual-note rows,
  all with:
  - `parser="docx-xml"`
  - `heuristic_primary="unknown"`
  - `hybrid_live_source="inline-llm"`
  - `old_label="medical"`
  and the classifier runtime then proved a second live heuristic-learning
  family beyond PDFs:
  - `force_inline_llm_for` now includes `docx-xml|unknown`
  - LightGBM retrained live to `training_rows=553`
  - readiness stayed green with `feedback_sources.manual-obsidian-note=13`
- after `fix: prefer exact manual override over filename collisions`, exact
  same-source reviewed feedback now beats newer reviewed-example rows that only
  share a filename; this fixed a real live `Appeal.docx` collision where a
  different reviewed example had been masking the manual correction
- after `feat: learn secondary label moves from vault curation`, generated-note
  manual feedback now remains effective when the primary label stays the same
  but the folder move adds a meaningful secondary label such as
  `medical/appeals`
- live proof on 2026-05-29 AKDT:
  - moved `Appeal - medical.md` into
    `01 Classified/medical/appeals/Appeal - medical - appeals.md`
  - ran manual-note sync to export the new same-primary secondary-label
    correction row
  - reran direct classification for `/srv/cloud-vault/mirrors/google1/Appeal.docx`
  - resulting note now lands at:
    `01 Classified/medical/appeals/Appeal - medical - appeals.md`
  - verified frontmatter now shows:
    - `primary_label="medical"`
    - `secondary_labels=["appeal"]`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `plain-text|unknown` family:
  - `google-drive-submission-test.txt` moved from `financial` to `technical`
  - `GE76_Raider_11UE(20230913).txt` moved from `letter` to `technical`
  - `twilio_2FA_recovery_code.txt` moved from `medical` to `technical`
  the live runtime then proved a third heuristic-learning family:
  - `force_inline_llm_for` now includes `plain-text|unknown`
  - LightGBM retrained live again to `training_rows=624`
  - readiness remained green with `feedback_sources.manual-obsidian-note=79`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/untitled folder/Downloads/twilio_2FA_recovery_code.txt`
  - resulting note now lands at:
    `01 Classified/technical/twilio_2FA_recovery_code - technical.md`
  - verified frontmatter now shows:
    - `primary_label="technical"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `spreadsheet-openpyxl|spreadsheet` family:
  - `MDM Enrollment DNS and Ports.xlsx` moved from `spreadsheet` to
    `technical`
  - `capital_gains_2024.xlsx` moved from `spreadsheet` to `financial`
  - `Actions Taken.xlsx` moved from `spreadsheet` to `medical/appeals`
  the live runtime then proved a fourth heuristic-learning family:
  - `force_inline_llm_for` now includes `spreadsheet-openpyxl|spreadsheet`
  - LightGBM retrained live from `631` to `641` approved teacher rows
  - readiness remained green with:
    - `teacher_reviewed_rows=683`
    - `teacher_approved_rows=641`
    - `feedback_sources.manual-obsidian-note=89`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/MDM Enrollment DNS and Ports.xlsx`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/capital_gains_2024.xlsx`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/FFS/Actions Taken.xlsx`
  - resulting notes now land at:
    - `01 Classified/technical/MDM Enrollment DNS and Ports - technical.md`
    - `01 Classified/financial/capital_gains_2024 - financial.md`
    - `01 Classified/medical/appeals/Actions Taken - medical - appeals.md`
  - verified frontmatter on each now shows:
    - `source_parser="spreadsheet-openpyxl"`
    - `heuristic_primary_hint="spreadsheet"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `docling|unknown` family:
  - `Request Denial Information.html` moved from `medical` to `insurance`
  - `your_messages.html` moved from `financial` to `personal`
  - `comments.html` moved from `insurance` to `personal`
  the live runtime then proved a fifth heuristic-learning family:
  - `force_inline_llm_for` now includes `docling|unknown`
  - LightGBM retrained live from `657` to `660` approved teacher rows
  - readiness remained green with:
    - `teacher_reviewed_rows=705`
    - `teacher_approved_rows=660`
    - `feedback_sources.manual-obsidian-note=101`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/FFS/Request Denial Information.html`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google2/meta-2025-May-02-05-47-46/facebook-kaymayers49-2025-05-02-6iqlH3mC/your_facebook_activity/messages/your_messages.html`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google2/meta-2025-May-02-05-47-46/facebook-kaymayers49-2025-05-02-6iqlH3mC/your_facebook_activity/comments_and_reactions/comments.html`
  - resulting notes now land at:
    - `01 Classified/insurance/Request Denial Information - insurance.md`
    - `01 Classified/personal/your_messages - personal.md`
    - `01 Classified/personal/comments - personal.md`
  - verified frontmatter on each now shows:
    - `source_parser="docling"`
    - `heuristic_primary_hint="unknown"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `docling-converted|unknown` family:
  - `B217C1 Buff Parchment.doc` moved from `medical` to `personal`
  - `Kay Vaginoplasty GRS Letter.doc` under `/google1/Surgery/` moved from
    `letter` to `medical`
  - `Kay Vaginoplasty GRS Letter.doc` under
    `/icloud/untitled folder/sort/combined/Surgery/` moved from `letter` to
    `medical`
  the live runtime then proved a sixth heuristic-learning family:
  - `force_inline_llm_for` now includes `docling-converted|unknown`
  - LightGBM retrained live through `training_rows=676`
  - readiness remained green with:
    - `teacher_reviewed_rows=726`
    - `teacher_approved_rows=677`
    - `feedback_sources.manual-obsidian-note=110`
    - `queue_depth=0`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/untitled folder/B217C1 Buff Parchment.doc`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/google1/Surgery/Kay Vaginoplasty GRS Letter.doc`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/untitled folder/sort/combined/Surgery/Kay Vaginoplasty GRS Letter.doc`
  - resulting notes now land at:
    - `01 Classified/personal/B217C1 Buff Parchment - personal.md`
    - `01 Classified/medical/Kay Vaginoplasty GRS Letter - medical.md`
  - verified frontmatter now shows:
    - `source_parser="docling-converted"`
    - `heuristic_primary_hint="unknown"`
    - `hybrid_live_source="manual-correction-override"`
- after three additional real manual moves on 2026-05-30 AKDT in the
  `pdftotext|unknown` family:
  - `New Patient Cognitive Questionnaire.pdf` moved from `medical` to `form`
  - `botox.pdf` moved from `medical` to `insurance`
  - `show.pdf` moved from `reimbursement-packet` to `tax-form`
  the live runtime then re-proved the seventh active parser family:
  - `force_inline_llm_for` includes `pdftotext|unknown`
  - fresh strong manual-note rows were exported for all three PDFs
  - LightGBM retrained live to `training_rows=698`
  - readiness remained green with:
    - `teacher_reviewed_rows=747`
    - `teacher_approved_rows=698`
    - `feedback_sources.manual-obsidian-note=120`
    - `queue_depth=0`
    - `real_ingestion_allowed=true`
- live downstream proof on 2026-05-30 AKDT:
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/Downloads/New Patient Cognitive Questionnaire.pdf`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/Scanned/botox.pdf`
  - reran direct classification for
    `/srv/cloud-vault/mirrors/icloud/Downloads/show.pdf`
  - resulting notes now land at:
    - `01 Classified/form/New Patient Cognitive Questionnaire - form.md`
    - `01 Classified/insurance/botox - insurance.md`
    - `01 Classified/tax-form/show - tax-form.md`
  - verified frontmatter now shows:
    - `source_parser="pdftotext"`
    - `heuristic_primary_hint="unknown"`
    - `hybrid_live_source="manual-correction-override"`
- rerunning the shadow-worker after that live rewrite did not append any newer
  bogus `financial -> financial` manual-note-move row for that receipt source
- `kayraspi` now carries only the legacy cloudsync Postgres database for the
  compute-only cutover; the old service and worker are stopped there
- an earlier pause request for the aggregate background scan was not kept as the
  live steady state; the scan is active again on `tichuml1`
- live proof on 2026-05-31 AKDT showed the public scan progressing inside one
  running batch rather than only at full batch boundaries
- `classification-worker` on `kayraspi` is intentionally stopped after reset
- aggregate mirror indexing has picked up both `google1` and `google2`
- `document-vault` is the canonical local Obsidian vault
- issue [#47](https://github.com/NeonButrfly/iCloudPlugin/issues/47) cleared
  the generated note surfaces in `document-vault` on 2026-05-30 AKDT before
  the next broad ingestion attempt:
  - `01 Classified`
  - `02 Needs Review`
  - `90 Attachments`
  - `_system/classifications`
  - `_system/extracted-markdown`
  - root `Classification Index.md`
- that reset intentionally preserved:
  - `.obsidian`
  - `00 Inbox`
  - `_system/templates`
  - `_system/training`
  - the source mirrors and indexed `files` table
- the smoke classification used
  `/srv/cloud-vault/mirrors/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx`
  and created an `appeal` note in `document-vault`
- `kayraspi2` remains the storage/share/proxy host

## Not Finished Yet

- prove and, if needed, finish the new source-derived repair path for the
  remaining legacy generated notes that still lack `source_parser` /
  `heuristic_primary_hint` / `hybrid_live_source` when their state rows are
  still queued or missing entirely
  ([#52](https://github.com/NeonButrfly/iCloudPlugin/issues/52),
  [#1](https://github.com/NeonButrfly/iCloudPlugin/issues/1))
- retire/archive the old standalone `local-doc-classifier` checkout after safe
  soak period ([#1](https://github.com/NeonButrfly/iCloudPlugin/issues/1))
- optionally move cloudsync Postgres off `kayraspi` later if the compute-only
  cutover soaks cleanly ([#1](https://github.com/NeonButrfly/iCloudPlugin/issues/1))
- keep the Codex final-arbiter path disabled until issue
  [#20](https://github.com/NeonButrfly/iCloudPlugin/issues/20) is fully
  implemented and deliberately enabled
- deploy and validate the new Cloudflare remote MCP slice once Cloudflare
  account auth is available in-session
  ([#48](https://github.com/NeonButrfly/iCloudPlugin/issues/48))
- decide whether the Worker itself will sit behind Cloudflare Access, another
  OAuth front door, or a different auth product before calling the external MCP
  path production-ready
  ([#48](https://github.com/NeonButrfly/iCloudPlugin/issues/48))

## Recent Commits That Matter

- `598ff3d50536bbf58e90abc79dc7000f4736a701`
  - `fix: harden classifier api role for live traffic`

- `379e4031c919e78816f5e5be6c3d6fee1156621c`
  - `fix: make classifier image support API role startup`

- `09bcf0e02cf8f66f24dab286e13af40522b65e8b`
  - `feat: support live classifier role cutover`

- `f85d291f69239589c99d4cca1b93d6c5fed3b8af`
  - `docs: consolidate workspace artifacts`

## Best Starting Point For A New Chat

1. Use `C:\Code\iCloudPlugin` as the workspace.
2. Read `docs/workspace-map.md`.
3. Read this file.
4. Treat `/srv/cloud-vault/document-vault` as the canonical Obsidian vault.
5. Assume:
   - `kayraspi2` is storage/share/proxy
   - `tichuml1` is classifier plus live cloudsync compute host
