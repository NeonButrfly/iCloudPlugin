import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from icloud_index_service.main import app


def test_health_endpoint_reports_ok():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
