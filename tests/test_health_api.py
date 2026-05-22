import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

import icloud_index_service.main as main_module


def test_health_endpoint_reports_ok(monkeypatch):
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)

    with TestClient(main_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_endpoint_reports_database_unavailable(monkeypatch):
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: False)

    with TestClient(main_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}


def test_app_startup_validates_database(monkeypatch):
    validation_calls: list[str] = []

    def fake_validate_database_configuration() -> None:
        validation_calls.append("validated")

    monkeypatch.setattr(main_module, "validate_database_configuration", fake_validate_database_configuration)

    with TestClient(main_module.app):
        pass

    assert validation_calls == ["validated"]


def test_plugin_mcp_wiring_uses_real_plugin_server_module():
    repo_root = Path(__file__).resolve().parents[1]
    config = json.loads((repo_root / "plugins/icloud-drive/.mcp.json").read_text())
    server = config["mcpServers"]["icloud-drive"]

    assert server["command"] == "python"
    assert server["args"][0] == "-c"
    assert "icloud_plugin_mcp.server" in server["args"][1]

    result = subprocess.run(
        [server["command"], *server["args"], "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "icloud index service" in result.stdout.lower()


def test_compose_db_host_port_override_keeps_internal_postgres_port():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ | {"POSTGRES_PUBLISHED_PORT": "6543"}
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    postgres_port = config["services"]["postgres"]["ports"][0]
    service_env = config["services"]["service"]["environment"]

    assert postgres_port["target"] == 5432
    assert postgres_port["published"] == "6543"
    assert service_env["POSTGRES_PORT"] == "5432"


def test_compose_runs_migrations_before_service_and_worker():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    services = config["services"]
    migrate_service = services["migrate"]
    service_depends_on = services["service"]["depends_on"]
    worker_depends_on = services["worker"]["depends_on"]

    assert migrate_service["command"] == ["uv", "run", "alembic", "upgrade", "head"]
    assert service_depends_on["migrate"]["condition"] == "service_completed_successfully"
    assert worker_depends_on["migrate"]["condition"] == "service_completed_successfully"


def test_compose_passes_icloud_auth_environment_to_service_and_worker():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ | {
        "ICLOUD_APPLE_ID": "user@example.com",
        "ICLOUD_APPLE_PASSWORD": "secret",
    }
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    service_env = config["services"]["service"]["environment"]
    worker_env = config["services"]["worker"]["environment"]

    for container_env in (service_env, worker_env):
        assert container_env["ICLOUD_APPLE_ID"] == "user@example.com"
        assert container_env["ICLOUD_APPLE_PASSWORD"] == "secret"
        assert container_env["ICLOUD_COOKIE_DIRECTORY"] == ".runtime/pyicloud"
        assert container_env["ICLOUD_MAX_DOWNLOAD_BYTES"] == "1048576"


def test_compose_passes_filesystem_mirror_environment_to_service_and_worker():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ | {
        "ICLOUD_SOURCE_MODE": "filesystem-mirror",
        "ICLOUD_MIRROR_ROOT": "/srv/cloud-vault/mirrors/icloud",
    }
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    service_env = config["services"]["service"]["environment"]
    worker_env = config["services"]["worker"]["environment"]

    for container_env in (service_env, worker_env):
        assert container_env["ICLOUD_SOURCE_MODE"] == "filesystem-mirror"
        assert container_env["ICLOUD_MIRROR_ROOT"] == "/srv/cloud-vault/mirrors/icloud"


def test_compose_mounts_cloud_vault_into_service_and_worker_for_mirror_mode():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    service_volumes = config["services"]["service"]["volumes"]
    worker_volumes = config["services"]["worker"]["volumes"]

    expected_mount = {
        "type": "bind",
        "source": "/srv/cloud-vault",
        "target": "/srv/cloud-vault",
    }

    for volume_list in (service_volumes, worker_volumes):
        assert any(
            volume["type"] == expected_mount["type"]
            and volume["source"] == expected_mount["source"]
            and volume["target"] == expected_mount["target"]
            and volume.get("read_only") is True
            for volume in volume_list
        )


def test_compose_includes_classification_worker_with_classifier_environment():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ | {
        "CLASSIFIER_API_URL": "http://192.168.50.196:4319",
        "CLASSIFIER_API_TOKEN": "top-secret",
        "CLASSIFICATION_SUBMISSION_ENABLED": "true",
        "CLASSIFICATION_SUBMISSION_CONCURRENCY": "2",
        "CLASSIFIER_VAULT_ROOT": "/srv/cloud-vault/local-doc-classifier-vault",
    }
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    services = config["services"]
    classification_worker = services["classification-worker"]
    worker_env = classification_worker["environment"]

    assert classification_worker["command"] == [
        "uv",
        "run",
        "python",
        "-m",
        "icloud_index_service.classification_worker",
    ]
    assert worker_env["CLASSIFIER_API_URL"] == "http://192.168.50.196:4319"
    assert worker_env["CLASSIFIER_API_TOKEN"] == "top-secret"
    assert worker_env["CLASSIFICATION_SUBMISSION_ENABLED"] == "true"
    assert worker_env["CLASSIFICATION_SUBMISSION_CONCURRENCY"] == "2"
    assert worker_env["CLASSIFIER_VAULT_ROOT"] == "/srv/cloud-vault/local-doc-classifier-vault"


def test_compose_mounts_cloud_vault_writable_into_classification_worker():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    classification_worker_volumes = config["services"]["classification-worker"]["volumes"]

    assert any(
        volume["type"] == "bind"
        and volume["source"] == "/srv/cloud-vault"
        and volume["target"] == "/srv/cloud-vault"
        and volume.get("read_only") is not True
        for volume in classification_worker_volumes
    )


def test_app_import_registers_sync_run_metadata_for_refresh_jobs():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ | {"PYTHONPATH": str(repo_root / "src")}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from icloud_index_service.main import app; "
                "from icloud_index_service.models.base import Base; "
                "print(sorted(Base.metadata.tables.keys()))"
            ),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "sync_runs" in result.stdout
