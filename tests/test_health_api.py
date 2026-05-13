import json
import os
import subprocess
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
