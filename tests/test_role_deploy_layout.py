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
    assert '- "${CLASSIFIER_API_WORKERS:-2}"' in compose_text


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
