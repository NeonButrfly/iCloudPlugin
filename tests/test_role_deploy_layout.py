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


def test_cloudsync_role_sync_assets_exist():
    repo_root = Path(__file__).resolve().parents[1]
    expected = [
        repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh",
        repo_root / "deploy" / "roles" / "cloudsync" / "run_targeted_classification_batch.sh",
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


def test_cloudsync_role_skips_dangling_google_drive_shortcuts():
    repo_root = Path(__file__).resolve().parents[1]
    sync_script = repo_root / "deploy" / "roles" / "cloudsync" / "cloud-vault-sync.sh"
    script_text = sync_script.read_text(encoding="utf-8")

    assert "--drive-skip-dangling-shortcuts" in script_text


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
    assert "postgres_service_running()" in script_text
    assert "docker run --rm \\" in script_text
    assert "--network host \\" in script_text
    assert 'postgres:16 \\' in script_text
    assert "CLASSIFICATION_SUBMISSION_CONCURRENCY" in script_text
    assert "run --rm --no-deps" in script_text
    assert "RUN_LIVE_SUMMARY" in script_text
    assert "--run-live-summary" in script_text
    assert "TARGETED_FEEDBACK_ONLY" in script_text
    assert "--targeted-feedback-only" in script_text
    assert 'CLASSIFICATION_BACKFILL_ENABLED=$([[ "${TARGETED_FEEDBACK_ONLY}" == "1" ]] && printf false || printf true)' in script_text
    assert "Recent completed rows overall:" in script_text
    assert "SUMMARY_JSON_PATH" in script_text
    assert "--summary-json" in script_text
    assert "write_summary_json" in script_text
    assert "'path', cj.path" in script_text
    assert "'path', cs.path" in script_text
    assert "'path', f.path" not in script_text
    assert 'docker rm -f "${container_id}" >/dev/null 2>&1 || true' in script_text
    assert "return 0" in script_text
    assert 'timeout "${WORKER_TIMEOUT_SECONDS}s" "${worker_command[@]}"' in script_text


def test_cloudsync_docs_reference_targeted_batch_helper():
    repo_root = Path(__file__).resolve().parents[1]
    role_readme = repo_root / "deploy" / "roles" / "cloudsync" / "README.md"
    operations_doc = repo_root / "docs" / "operations.md"

    assert "run_targeted_classification_batch.sh" in role_readme.read_text(encoding="utf-8")
    assert "run_targeted_classification_batch.sh" in operations_doc.read_text(encoding="utf-8")


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
    assert "- CODEX_ARBITER_ENABLED=${CODEX_ARBITER_ENABLED:-0}" in compose_text
    assert '- "${CLASSIFIER_API_WORKERS:-4}"' in compose_text


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
    assert services["classifier-api"]["environment"]["CODEX_ARBITER_ENABLED"] == "0"
