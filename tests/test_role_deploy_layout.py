from pathlib import Path
import json
import subprocess


def test_role_docs_exist_for_cloudsync_classifier_and_combined():
    repo_root = Path(__file__).resolve().parents[1]
    expected = [
        repo_root / "deploy" / "roles" / "cloudsync" / "README.md",
        repo_root / "deploy" / "roles" / "classifier" / "README.md",
        repo_root / "deploy" / "roles" / "combined" / "README.md",
    ]

    assert all(path.exists() for path in expected)


def test_classifier_role_readiness_helper_exists():
    repo_root = Path(__file__).resolve().parents[1]
    helper = repo_root / "deploy" / "roles" / "classifier" / "report_codex_arbiter_readiness.sh"

    assert helper.exists()


def test_classifier_role_codex_smoke_helper_exists():
    repo_root = Path(__file__).resolve().parents[1]
    helper = repo_root / "deploy" / "roles" / "classifier" / "run_codex_arbiter_smoke.sh"

    assert helper.exists()


def test_classifier_role_learning_maintenance_helper_exists():
    repo_root = Path(__file__).resolve().parents[1]
    helper = repo_root / "deploy" / "roles" / "classifier" / "run_learning_maintenance.sh"

    assert helper.exists()


def test_cloudsync_role_sync_assets_exist():
    repo_root = Path(__file__).resolve().parents[1]
    expected = [
        repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh",
        repo_root / "deploy" / "roles" / "cloudsync" / "install_storage_host_sync_assets.sh",
        repo_root / "deploy" / "roles" / "cloudsync" / "run_targeted_classification_batch.sh",
        repo_root / "deploy" / "roles" / "cloudsync" / "report_live_status.sh",
        repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.service",
        repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.timer",
    ]

    assert all(path.exists() for path in expected)


def test_cloudsync_role_uses_remote_preferred_initial_resync_for_google_mirrors():
    repo_root = Path(__file__).resolve().parents[1]
    sync_script = repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh"
    script_text = sync_script.read_text(encoding="utf-8")

    assert 'REMOTE_ICLOUD_INITIAL_RESYNC_MODE="${REMOTE_ICLOUD_INITIAL_RESYNC_MODE:-path2}"' in script_text
    assert 'REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE="${REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE:-path1}"' in script_text
    assert 'REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE="${REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE:-path1}"' in script_text
    assert 'run_bisync "${REMOTE_GOOGLE_1}" "${REMOTE_GOOGLE_1}:" "${VAULT_MOUNT}/mirrors/google1" "${LOG_DIR}/google1.log" "${REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE}"' in script_text
    assert 'run_bisync "${REMOTE_GOOGLE_2}" "${REMOTE_GOOGLE_2}:" "${VAULT_MOUNT}/mirrors/google2" "${LOG_DIR}/google2.log" "${REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE}"' in script_text


def test_cloudsync_role_allows_google_mass_deletes_but_keeps_icloud_guarded():
    repo_root = Path(__file__).resolve().parents[1]
    sync_script = repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh"
    script_text = sync_script.read_text(encoding="utf-8")

    assert 'REMOTE_ICLOUD_ALLOW_MASS_DELETE="${REMOTE_ICLOUD_ALLOW_MASS_DELETE:-false}"' in script_text
    assert 'REMOTE_GOOGLE_1_ALLOW_MASS_DELETE="${REMOTE_GOOGLE_1_ALLOW_MASS_DELETE:-true}"' in script_text
    assert 'REMOTE_GOOGLE_2_ALLOW_MASS_DELETE="${REMOTE_GOOGLE_2_ALLOW_MASS_DELETE:-true}"' in script_text
    assert 'if is_truthy "${allow_mass_delete}"; then' in script_text
    assert "bisync_args+=(--force)" in script_text
    assert 'Mass-delete guard disabled for ${remote_name}; allowing intentional large delete waves.' in script_text


def test_cloudsync_role_skips_dangling_google_drive_shortcuts():
    repo_root = Path(__file__).resolve().parents[1]
    sync_script = repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh"
    script_text = sync_script.read_text(encoding="utf-8")

    assert "--drive-skip-dangling-shortcuts" in script_text


def test_cloudsync_role_can_force_rclone_ipv4_for_storage_host_sync():
    repo_root = Path(__file__).resolve().parents[1]
    sync_script = repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh"
    script_text = sync_script.read_text(encoding="utf-8")

    assert 'RCLONE_FORCE_IPV4="${RCLONE_FORCE_IPV4:-true}"' in script_text
    assert "RCLONE_NETWORK_ARGS=()" in script_text
    assert 'RCLONE_NETWORK_ARGS+=(--bind 0.0.0.0)' in script_text
    assert 'rclone lsf "${remote_name}:" "${RCLONE_NETWORK_ARGS[@]}" --max-depth 1' in script_text
    assert 'rclone bisync "${remote_path}" "${dest_path}" \\' in script_text
    assert '"${RCLONE_NETWORK_ARGS[@]}" \\' in script_text


def test_cloudsync_sync_script_writes_machine_readable_status_artifact():
    repo_root = Path(__file__).resolve().parents[1]
    sync_script = repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh"
    script_text = sync_script.read_text(encoding="utf-8")

    assert 'STATUS_FILE="${STATUS_FILE:-${STATUS_DIR}/cloud-vault-sync-status.json}"' in script_text
    assert 'REMOTE_ICLOUD_REQUIRED="${REMOTE_ICLOUD_REQUIRED:-true}"' in script_text
    assert 'REMOTE_GOOGLE_1_REQUIRED="${REMOTE_GOOGLE_1_REQUIRED:-false}"' in script_text
    assert 'REMOTE_GOOGLE_2_REQUIRED="${REMOTE_GOOGLE_2_REQUIRED:-false}"' in script_text
    assert "record_sync_status()" in script_text
    assert "record_remote_failure()" in script_text
    assert 'FAIL_ON_OPTIONAL_REMOTE_FAILURE="${FAIL_ON_OPTIONAL_REMOTE_FAILURE:-false}"' in script_text
    assert "compute_run_exit_code()" in script_text
    assert 'if (( REQUIRED_REMOTE_FAILURE_COUNT > 0 )); then' in script_text
    assert 'if is_truthy "${FAIL_ON_OPTIONAL_REMOTE_FAILURE}" && (( OPTIONAL_REMOTE_FAILURE_COUNT > 0 )); then' in script_text
    assert 'write_sync_status_file "${final_exit_code}"' in script_text
    assert 'exit "${final_exit_code}"' in script_text
    assert "write_sync_status_file()" in script_text
    assert '"overall_status": overall_status' in script_text
    assert '"required_failures_present": bool(required_failures)' in script_text


def test_cloudsync_storage_host_installer_covers_sync_assets_and_systemd_flow():
    repo_root = Path(__file__).resolve().parents[1]
    installer = (
        repo_root / "deploy" / "roles" / "cloudsync" / "install_storage_host_sync_assets.sh"
    )
    script_text = installer.read_text(encoding="utf-8")

    assert 'SYNC_SCRIPT_SOURCE="${SYNC_SCRIPT_SOURCE:-${SCRIPT_DIR}/cloud-vault-sync.sh}"' in script_text
    assert 'SYNC_SERVICE_SOURCE="${SYNC_SERVICE_SOURCE:-${SCRIPT_DIR}/cloud-vault-sync.service}"' in script_text
    assert 'SYNC_TIMER_SOURCE="${SYNC_TIMER_SOURCE:-${SCRIPT_DIR}/cloud-vault-sync.timer}"' in script_text
    assert 'SCRIPT_TARGET="${SCRIPT_TARGET:-/usr/local/bin/cloud-vault-sync.sh}"' in script_text
    assert 'SERVICE_TARGET="${SERVICE_TARGET:-/etc/systemd/system/cloud-vault-sync.service}"' in script_text
    assert 'TIMER_TARGET="${TIMER_TARGET:-/etc/systemd/system/cloud-vault-sync.timer}"' in script_text
    assert 'SUDO_PASSWORD="${SUDO_PASSWORD:-}"' in script_text
    assert "sudo_command()" in script_text
    assert 'printf \'%s\\n\' "${SUDO_PASSWORD}" | sudo -S "$@"' in script_text
    assert 'sudo_command install -m "${mode}" "${source_path}" "${target_path}"' in script_text
    assert 'sudo_command systemctl daemon-reload' in script_text
    assert 'sudo_command systemctl enable --now "$(basename "${TIMER_TARGET}")"' in script_text
    assert "--run-sync-after-install" in script_text
    assert 'sudo_command systemctl start "$(basename "${SERVICE_TARGET}")"' in script_text


def test_cloudsync_targeted_batch_helper_restores_queue_state():
    repo_root = Path(__file__).resolve().parents[1]
    helper_script = (
        repo_root / "deploy" / "roles" / "cloudsync" / "run_targeted_classification_batch.sh"
    )
    script_text = helper_script.read_text(encoding="utf-8")

    assert "DEFER_PREFIX" in script_text
    assert "FOCUS_PREFIX" in script_text
    assert 'POSTGRES_HOST="${POSTGRES_HOST:-postgres}"' in script_text
    assert 'POSTGRES_PORT="${POSTGRES_PORT:-5432}"' in script_text
    assert 'POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-change-me}"' in script_text
    assert "next_attempt_at" in script_text
    assert "trap cleanup EXIT" in script_text
    assert "load_env_file()" in script_text
    assert "source <(tr -d '\\r' < \"${ENV_FILE}\")" in script_text
    assert 'SUDO_PASSWORD="${SUDO_PASSWORD:-}"' in script_text
    assert "docker_command()" in script_text
    assert 'printf \'%s\\n\' "${SUDO_PASSWORD}" | sudo -S docker "$@"' in script_text
    assert "postgres_service_running()" in script_text
    assert "docker_command run --rm \\" in script_text
    assert "--network host \\" in script_text
    assert 'postgres:16 \\' in script_text
    assert "CLASSIFICATION_SUBMISSION_CONCURRENCY" in script_text
    assert "run --rm --no-deps" in script_text
    assert "run_worker_command()" in script_text
    assert "RUN_LIVE_SUMMARY" in script_text
    assert "--run-live-summary" in script_text
    assert "TARGETED_FEEDBACK_ONLY" in script_text
    assert "--targeted-feedback-only" in script_text
    assert "RECONCILIATION_ONLY" in script_text
    assert "--reconciliation-only" in script_text
    assert "RECONCILIATION_LIMIT" in script_text
    assert "--reconciliation-limit" in script_text
    assert 'CLASSIFICATION_BACKFILL_ENABLED=$([[ "${TARGETED_FEEDBACK_ONLY}" == "1" ]] && printf false || printf true)' in script_text
    assert "Recent completed rows overall:" in script_text
    assert "SUMMARY_JSON_PATH" in script_text
    assert "--summary-json" in script_text
    assert "write_summary_json" in script_text
    assert "capture_generated_note_context_json()" in script_text
    assert "collect_generated_note_context_gaps" in script_text
    assert "print_generated_note_context_summary" in script_text
    assert '"before_generated_note_context_gaps": parse_json_env("BEFORE_GENERATED_NOTE_CONTEXT_JSON", {})' in script_text
    assert '"after_generated_note_context_gaps": parse_json_env("AFTER_GENERATED_NOTE_CONTEXT_JSON", {})' in script_text
    assert '"reconciliation_result": parse_json_env("RECONCILIATION_RESULT_JSON", {})' in script_text
    assert "run_reconciliation_command()" in script_text
    assert "run_vault_reconciliation_once" in script_text
    assert "run_reconciliation_pass()" in script_text
    assert "Skipping queue defer/apply path because reconciliation-only mode is enabled" in script_text
    assert "'path', cj.path" in script_text
    assert "'path', cs.path" in script_text
    assert "'path', f.path" not in script_text
    assert 'docker_command rm -f "${container_id}" >/dev/null 2>&1 || true' in script_text
    assert "return 0" in script_text
    assert 'while kill -0 "${worker_pid}" >/dev/null 2>&1; do' in script_text
    assert 'kill "${worker_pid}" >/dev/null 2>&1 || true' in script_text


def test_cloudsync_live_status_helper_covers_compute_only_status_surfaces():
    repo_root = Path(__file__).resolve().parents[1]
    helper_script = (
        repo_root / "deploy" / "roles" / "cloudsync" / "report_live_status.sh"
    )
    script_text = helper_script.read_text(encoding="utf-8")

    assert 'ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/.env.live}"' in script_text
    assert 'CLASSIFIER_ENV_FILE="${CLASSIFIER_ENV_FILE:-${REPO_ROOT}/deploy/roles/classifier/.env.live}"' in script_text
    assert 'POSTGRES_HOST="${POSTGRES_HOST:-postgres}"' in script_text
    assert 'SUDO_PASSWORD="${SUDO_PASSWORD:-}"' in script_text
    assert "docker_command()" in script_text
    assert 'printf \'%s\\n\' "${SUDO_PASSWORD}" | sudo -S docker "$@"' in script_text
    assert "postgres_service_running()" in script_text
    assert 'docker_command run --rm \\' in script_text
    assert 'postgres:16 \\' in script_text
    assert 'capture_service_json "/health"' in script_text
    assert 'capture_service_json "/refresh/status"' in script_text
    assert "read_env_value()" in script_text
    assert 'ENV_FILE_CLASSIFIER_API_TOKEN="$(read_env_value "${ENV_FILE}" "CLASSIFIER_API_TOKEN")"' in script_text
    assert 'CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN="$(read_env_value "${CLASSIFIER_ENV_FILE}" "CLASSIFIER_API_TOKEN")"' in script_text
    assert 'EFFECTIVE_CLASSIFIER_API_TOKEN="${CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN:-${ENV_FILE_CLASSIFIER_API_TOKEN:-${CLASSIFIER_API_TOKEN:-}}}"' in script_text
    assert 'CLASSIFIER_HEALTH_JSON="$(capture_http_json "${CLASSIFIER_HEALTH_URL}" -H "X-API-Key: ${EFFECTIVE_CLASSIFIER_API_TOKEN}")"' in script_text
    assert "collect_token_config_json()" in script_text
    assert 'TOKEN_CONFIG_JSON="$(collect_token_config_json)"' in script_text
    assert "classification_job_counts_sql()" in script_text
    assert "classification_state_counts_sql()" in script_text
    assert "classification_state_status_by_path_sql()" in script_text
    assert 'export CLASSIFICATION_STATE_PATH_STATUS_JSON_PAYLOAD="${CLASSIFICATION_STATE_PATH_STATUS_JSON}"' in script_text
    assert "provider_counts_sql()" in script_text
    assert "collect_vault_counts_json()" in script_text
    assert "collect_generated_note_context_json()" in script_text
    assert 'MIRROR_ROOT="${MIRROR_ROOT:-${ICLOUD_MIRROR_MOUNT_SOURCE:-/mnt/cloud-vault}/mirrors}"' in script_text
    assert "--mirror-root" in script_text
    assert '"generated_note_context_gaps": parse_json_env("GENERATED_NOTE_CONTEXT_JSON")' in script_text
    assert '"token_config": parse_json_env("TOKEN_CONFIG_JSON")' in script_text
    assert 'CLOUD_VAULT_SYNC_STATUS_PATH="${CLOUD_VAULT_SYNC_STATUS_PATH:-/mnt/cloud-vault/logs/cloud-vault-sync-status.json}"' in script_text
    assert "collect_sync_status_json()" in script_text
    assert '"cloud_vault_sync": parse_json_env("CLOUD_VAULT_SYNC_STATUS_JSON")' in script_text
    assert "Wrote summary JSON" in script_text


def test_cloudsync_docs_reference_targeted_batch_helper():
    repo_root = Path(__file__).resolve().parents[1]
    role_readme = repo_root / "deploy" / "roles" / "cloudsync" / "README.md"
    operations_doc = repo_root / "docs" / "operations.md"

    assert "run_targeted_classification_batch.sh" in role_readme.read_text(encoding="utf-8")
    assert "report_live_status.sh" in role_readme.read_text(encoding="utf-8")
    assert "RCLONE_FORCE_IPV4" in role_readme.read_text(encoding="utf-8")
    assert "FAIL_ON_OPTIONAL_REMOTE_FAILURE" in role_readme.read_text(encoding="utf-8")
    assert "#85" in role_readme.read_text(encoding="utf-8")
    assert "#83" in role_readme.read_text(encoding="utf-8")
    assert "--resync --resync-mode path1" in role_readme.read_text(encoding="utf-8")
    assert "REMOTE_GOOGLE_1_ALLOW_MASS_DELETE" in role_readme.read_text(encoding="utf-8")
    assert "REMOTE_GOOGLE_2_ALLOW_MASS_DELETE" in role_readme.read_text(encoding="utf-8")
    assert "POSTGRES_HOST=postgres" in role_readme.read_text(encoding="utf-8")
    assert "run_targeted_classification_batch.sh" in operations_doc.read_text(encoding="utf-8")
    assert "report_live_status.sh" in operations_doc.read_text(encoding="utf-8")
    assert "RCLONE_FORCE_IPV4" in operations_doc.read_text(encoding="utf-8")
    assert "FAIL_ON_OPTIONAL_REMOTE_FAILURE" in operations_doc.read_text(encoding="utf-8")
    assert "#85" in operations_doc.read_text(encoding="utf-8")
    assert "#83" in operations_doc.read_text(encoding="utf-8")
    assert "--resync --resync-mode path1" in operations_doc.read_text(encoding="utf-8")
    assert "REMOTE_GOOGLE_1_ALLOW_MASS_DELETE" in operations_doc.read_text(encoding="utf-8")
    assert "REMOTE_GOOGLE_2_ALLOW_MASS_DELETE" in operations_doc.read_text(encoding="utf-8")
    assert "POSTGRES_HOST=postgres" in operations_doc.read_text(encoding="utf-8")


def test_reindex_helpers_match_role_based_cloudsync_runtime():
    repo_root = Path(__file__).resolve().parents[1]
    shell_helper = repo_root / "scripts" / "reindex-icloud-index.sh"
    powershell_helper = repo_root / "scripts" / "reindex-icloud-index.ps1"

    shell_text = shell_helper.read_text(encoding="utf-8")
    powershell_text = powershell_helper.read_text(encoding="utf-8")

    assert 'ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/.env.live}"' in shell_text
    assert 'COMPOSE_PROJECT="${COMPOSE_PROJECT:-cloudsync}"' in shell_text
    assert 'COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/docker-compose.yml}"' in shell_text
    assert 'SUDO_PASSWORD="${SUDO_PASSWORD:-}"' in shell_text
    assert "docker_command()" in shell_text
    assert 'printf \'%s\\n\' "${SUDO_PASSWORD}" | sudo -S docker "$@"' in shell_text
    assert "source <(tr -d '\\r' < " in shell_text
    assert 'docker_command run --rm \\' in shell_text
    assert '--network host \\' in shell_text
    assert 'postgres:16 \\' in shell_text
    assert 'docker_compose up -d postgres migrate service worker classification-worker' in shell_text
    assert 'docker_compose up -d --no-deps service worker classification-worker' in shell_text
    assert 'TRUNCATE TABLE classification_jobs, classification_states, extracted_contents, files, jobs, sync_runs RESTART IDENTITY CASCADE;' in shell_text
    assert 'curl_args+=(-H "Authorization: Bearer ${PLUGIN_API_TOKEN}")' in shell_text
    assert 'PLUGIN_SERVICE_URL="${PLUGIN_SERVICE_URL:-}"' in shell_text
    assert 'Authorization: Bearer [redacted]' in shell_text
    assert '--dry-run' in shell_text
    assert '--yes' in shell_text
    assert 'This action is destructive. Re-run with --yes to confirm' in shell_text

    assert 'deploy/roles/cloudsync/.env.live' in powershell_text
    assert 'deploy/roles/cloudsync/docker-compose.yml' in powershell_text
    assert '$script:ComposeProject = if ($ComposeProject) { $ComposeProject } else { "cloudsync" }' in powershell_text
    assert 'classification-worker' in powershell_text
    assert 'TRUNCATE TABLE classification_jobs, classification_states, extracted_contents, files, jobs, sync_runs RESTART IDENTITY CASCADE;' in powershell_text
    assert 'Authorization: Bearer $script:PluginApiToken' in powershell_text
    assert 'Authorization: Bearer [redacted]' in powershell_text
    assert '$script:PluginServiceUrl = if ($env:PLUGIN_SERVICE_URL)' in powershell_text
    assert 'This action is destructive. Re-run with -Yes to confirm' in powershell_text
    assert '[switch]$DryRun' in powershell_text
    assert '[switch]$Yes' in powershell_text


def test_product_readiness_report_script_exists_and_docs_reference_it():
    repo_root = Path(__file__).resolve().parents[1]
    report_script = repo_root / "scripts" / "report_product_readiness.py"
    operations_doc = repo_root / "docs" / "operations.md"
    handoff_doc = repo_root / "docs" / "chat-handoff.md"

    assert report_script.exists()
    assert "report_product_readiness.py" in operations_doc.read_text(encoding="utf-8")
    assert "report_product_readiness.py" in handoff_doc.read_text(encoding="utf-8")


def test_remote_mcp_deploy_workflow_exists_and_uses_repo_verify_helpers():
    repo_root = Path(__file__).resolve().parents[1]
    workflow = repo_root / ".github" / "workflows" / "remote-mcp-deploy.yml"
    bootstrap_helper = (
        repo_root / "cloudflare" / "remote-mcp" / "scripts" / "bootstrap-github-secrets.mjs"
    )
    operations_doc = repo_root / "docs" / "operations.md"
    handoff_doc = repo_root / "docs" / "chat-handoff.md"

    workflow_text = workflow.read_text(encoding="utf-8")
    bootstrap_text = bootstrap_helper.read_text(encoding="utf-8")

    assert workflow.exists()
    assert bootstrap_helper.exists()
    assert "workflow_dispatch:" in workflow_text
    assert "deploy-and-verify" in workflow_text
    assert "mcp-verify-only" in workflow_text
    assert "plan" in workflow_text
    assert "node scripts/deploy-and-verify.mjs --plan --json" in workflow_text
    assert "node scripts/deploy-and-verify.mjs --sync-secrets --json" in workflow_text
    assert "node scripts/verify-mcp-tools.mjs" in workflow_text
    assert "CLOUDFLARE_API_TOKEN" in workflow_text
    assert "REMOTE_MCP_ORIGIN_BASE_URL" in workflow_text
    assert "REMOTE_MCP_ORIGIN_API_TOKEN" in workflow_text
    assert "REMOTE_MCP_PUBLIC_BASE_URL" in workflow_text
    assert "${{ vars.REMOTE_MCP_PUBLIC_BASE_URL }}" in workflow_text
    assert "REMOTE_MCP_VERIFY_HEADERS_JSON" in workflow_text
    assert "CF_ACCESS_CLIENT_ID" in workflow_text
    assert "CF_ACCESS_CLIENT_SECRET" in workflow_text
    assert "CF_ACCESS_TOKEN" in workflow_text
    assert "remote-mcp-deploy" in workflow_text
    assert 'DEFAULT_REPO = "NeonButrfly/iCloudPlugin"' in bootstrap_text
    assert '"REMOTE_MCP_ORIGIN_BASE_URL"' in bootstrap_text
    assert '"REMOTE_MCP_ORIGIN_API_TOKEN"' in bootstrap_text
    assert '"REMOTE_MCP_PUBLIC_BASE_URL"' in bootstrap_text
    assert '["secret", "set", entry.target_name, "--repo", plan.repo]' in bootstrap_text
    assert '["variable", "set", entry.target_name, "--repo", plan.repo]' in bootstrap_text
    assert "remote-mcp-deploy.yml" in operations_doc.read_text(encoding="utf-8")
    assert "bootstrap-github-secrets.mjs" in operations_doc.read_text(encoding="utf-8")
    assert "remote-mcp-deploy.yml" in handoff_doc.read_text(encoding="utf-8")
    assert "bootstrap-github-secrets.mjs" in handoff_doc.read_text(encoding="utf-8")


def test_role_compose_files_exist_for_cloudsync_classifier_and_combined():
    repo_root = Path(__file__).resolve().parents[1]
    expected = [
        repo_root / "deploy" / "roles" / "cloudsync" / "docker-compose.yml",
        repo_root / "deploy" / "roles" / "classifier" / "docker-compose.yml",
        repo_root / "deploy" / "roles" / "combined" / "docker-compose.yml",
    ]

    assert all(path.exists() for path in expected)


def test_cloudsync_role_compose_targets_sync_side_services_only():
    repo_root = Path(__file__).resolve().parents[1]
    role_compose = repo_root / "deploy" / "roles" / "cloudsync" / "docker-compose.yml"
    result = subprocess.run(
        ["docker", "compose", "-f", str(role_compose), "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    services = json.loads(result.stdout)["services"]
    assert {"postgres", "migrate", "service", "worker", "classification-worker"} <= set(services)
    assert "ollama" not in services
    assert "classifier-api" not in services


def test_cloudsync_role_service_and_worker_mounts_are_writable_for_document_vault_mutations():
    repo_root = Path(__file__).resolve().parents[1]
    role_compose = repo_root / "deploy" / "roles" / "cloudsync" / "docker-compose.yml"
    compose_text = role_compose.read_text(encoding="utf-8")

    assert '${ICLOUD_MIRROR_MOUNT_SOURCE:-/mnt/cloud-vault}:/srv/cloud-vault\n' in compose_text
    assert '${ICLOUD_MIRROR_MOUNT_SOURCE:-/mnt/cloud-vault}:/srv/cloud-vault:ro' not in compose_text


def test_root_and_combined_service_mounts_are_writable_for_document_vault_mutations():
    repo_root = Path(__file__).resolve().parents[1]
    root_compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    combined_compose = (
        repo_root / "deploy" / "roles" / "combined" / "docker-compose.yml"
    ).read_text(encoding="utf-8")

    assert '${ICLOUD_MIRROR_MOUNT_SOURCE:-/srv/cloud-vault}:/srv/cloud-vault\n' in root_compose
    assert '${ICLOUD_MIRROR_MOUNT_SOURCE:-/mnt/cloud-vault}:/srv/cloud-vault\n' in combined_compose


def test_classifier_role_compose_targets_classifier_side_services_only():
    repo_root = Path(__file__).resolve().parents[1]
    role_compose = repo_root / "deploy" / "roles" / "classifier" / "docker-compose.yml"
    result = subprocess.run(
        ["docker", "compose", "-f", str(role_compose), "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    services = json.loads(result.stdout)["services"]
    assert {"ollama", "classifier-api"} <= set(services)
    assert "postgres" not in services
    assert "service" not in services

    init_result = subprocess.run(
        ["docker", "compose", "--profile", "init", "-f", str(role_compose), "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert init_result.returncode == 0
    init_services = json.loads(init_result.stdout)["services"]
    assert "model-init" in init_services


def test_classifier_role_compose_allows_config_dir_override_for_live_migration():
    repo_root = Path(__file__).resolve().parents[1]
    role_compose = repo_root / "deploy" / "roles" / "classifier" / "docker-compose.yml"
    compose_text = role_compose.read_text(encoding="utf-8")

    assert "${CLASSIFIER_CONFIG_DIR:-../../../config}:/config:ro" in compose_text


def test_classifier_role_compose_disables_shadow_worker_and_supports_multiple_api_workers():
    repo_root = Path(__file__).resolve().parents[1]
    role_compose = repo_root / "deploy" / "roles" / "classifier" / "docker-compose.yml"
    compose_text = role_compose.read_text(encoding="utf-8")

    assert "- ENABLE_SHADOW_WORKER=${ENABLE_SHADOW_WORKER:-0}" in compose_text
    assert "- CLASSIFIER_FORCE_REAL_INGESTION=${CLASSIFIER_FORCE_REAL_INGESTION:-0}" in compose_text
    assert "- CODEX_ARBITER_ENABLED=${CODEX_ARBITER_ENABLED:-0}" in compose_text
    assert "- CODEX_ARBITER_COMMAND=${CODEX_ARBITER_COMMAND:-codex exec}" in compose_text
    assert "- CODEX_ARBITER_TIMEOUT_SECONDS=${CODEX_ARBITER_TIMEOUT_SECONDS:-120}" in compose_text
    assert '- "${CLASSIFIER_API_WORKERS:-4}"' in compose_text


def test_classifier_role_docs_reference_codex_arbiter_readiness_helper():
    repo_root = Path(__file__).resolve().parents[1]
    role_readme = repo_root / "deploy" / "roles" / "classifier" / "README.md"
    operations_doc = repo_root / "docs" / "operations.md"

    assert "report_codex_arbiter_readiness.sh" in role_readme.read_text(encoding="utf-8")
    assert "report_codex_arbiter_readiness.sh" in operations_doc.read_text(encoding="utf-8")


def test_classifier_role_smoke_helper_supports_request_scoped_codex_override():
    repo_root = Path(__file__).resolve().parents[1]
    helper = repo_root / "deploy" / "roles" / "classifier" / "run_codex_arbiter_smoke.sh"
    script_text = helper.read_text(encoding="utf-8")

    assert 'ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/classifier/.env.live}"' in script_text
    assert 'READINESS_HELPER="${READINESS_HELPER:-${SCRIPT_DIR}/report_codex_arbiter_readiness.sh}"' in script_text
    assert "--source-relative-path" in script_text
    assert "--canonical-source-path" in script_text
    assert "--json-out" in script_text
    assert "--request-timeout-seconds" in script_text
    assert "--no-arbiter-override" in script_text
    assert 'CLASSIFIER_CLASSIFY_URL="${CLASSIFIER_CLASSIFY_URL:-http://127.0.0.1:${CLASSIFIER_API_PORT}/classify/source}"' in script_text
    assert 'curl_args+=(-F "enable_codex_arbiter_override=true")' in script_text
    assert 'CLASSIFIER_API_TOKEN is required to run the smoke classification.' in script_text
    assert '"enable_codex_arbiter_override": sys.argv[9].strip().lower() == "true"' in script_text


def test_classifier_role_docs_reference_codex_arbiter_smoke_helper():
    repo_root = Path(__file__).resolve().parents[1]
    role_readme = repo_root / "deploy" / "roles" / "classifier" / "README.md"
    operations_doc = repo_root / "docs" / "operations.md"

    assert "run_codex_arbiter_smoke.sh" in role_readme.read_text(encoding="utf-8")
    assert "run_codex_arbiter_smoke.sh" in operations_doc.read_text(encoding="utf-8")


def test_classifier_role_docs_reference_learning_maintenance_helper():
    repo_root = Path(__file__).resolve().parents[1]
    role_readme = repo_root / "deploy" / "roles" / "classifier" / "README.md"
    helper = repo_root / "deploy" / "roles" / "classifier" / "run_learning_maintenance.sh"
    helper_text = helper.read_text(encoding="utf-8")
    role_text = role_readme.read_text(encoding="utf-8")

    assert "run_learning_maintenance.sh" in role_text
    assert "learning-maintenance" in role_text
    assert "apps.classifier.learning_maintenance" in helper_text
    assert "--summary-json" in helper_text
    assert "LEARNING_MAINTENANCE_TRAIN_FROM_INDEX" in helper_text


def test_combined_role_compose_includes_sync_and_classifier_services():
    repo_root = Path(__file__).resolve().parents[1]
    role_compose = repo_root / "deploy" / "roles" / "combined" / "docker-compose.yml"
    result = subprocess.run(
        ["docker", "compose", "-f", str(role_compose), "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    services = json.loads(result.stdout)["services"]
    assert {"postgres", "service", "worker", "classification-worker", "ollama", "classifier-api"} <= set(services)
    assert services["classifier-api"]["environment"]["CLASSIFIER_FORCE_REAL_INGESTION"] == "0"
    assert services["classifier-api"]["environment"]["CODEX_ARBITER_ENABLED"] == "0"
    assert services["classifier-api"]["environment"]["CODEX_ARBITER_COMMAND"] == "codex exec"
    assert services["classifier-api"]["environment"]["CODEX_ARBITER_TIMEOUT_SECONDS"] == "120"
