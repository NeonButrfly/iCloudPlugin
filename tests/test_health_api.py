import json
import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

import icloud_index_service.main as main_module
from icloud_index_service.main import app


def test_health_endpoint_reports_ok():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_startup_validates_database_when_override_disabled(monkeypatch):
    validation_calls: list[str] = []

    def fake_validate_database_configuration() -> None:
        validation_calls.append("validated")

    monkeypatch.delenv("ICLOUD_INDEX_SKIP_DB_STARTUP_VALIDATION", raising=False)
    monkeypatch.setattr(main_module, "validate_database_configuration", fake_validate_database_configuration)

    with TestClient(main_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert validation_calls == ["validated"]


def test_plugin_mcp_wiring_uses_task1_owned_stub():
    repo_root = Path(__file__).resolve().parents[1]
    config = json.loads((repo_root / "plugins/icloud-drive/.mcp.json").read_text())
    server = config["mcpServers"]["icloud-drive"]

    assert "icloud_plugin_mcp" not in " ".join(server["args"])

    result = subprocess.run(
        [server["command"], *server["args"], "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "task 1" in result.stdout.lower()


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
