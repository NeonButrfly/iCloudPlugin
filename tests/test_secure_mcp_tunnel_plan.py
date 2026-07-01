from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_secure_mcp_tunnel_plan_reports_expected_chatgpt_path():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/secure_mcp_tunnel_plan.py", "--json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["connector_name"] == "iCloudPlugin"
    assert payload["local_mcp_command"] == "python scripts/run_chatgpt_mcp_server.py"
    assert payload["local_mcp_transport"] == "stdio"
    assert payload["service_url"] == "http://127.0.0.1:8080"
    assert payload["official_docs"]["secure_mcp_tunnel"].startswith(
        "https://developers.openai.com/api/docs/guides/secure-mcp-tunnels"
    )
    assert payload["official_docs"]["connect_from_chatgpt"].startswith(
        "https://developers.openai.com/apps-sdk/deploy/connect-chatgpt"
    )


def test_run_chatgpt_mcp_server_wraps_real_mcp_entrypoint():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/run_chatgpt_mcp_server.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "icloud index service" in result.stdout.lower()
