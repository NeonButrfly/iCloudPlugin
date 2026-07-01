from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_install_codex_plugin_reports_repo_marketplace_plan():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/install_codex_plugin.py", "--json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["plugin_name"] == "icloud-drive"
    assert payload["plugin_root"].endswith("plugins\\icloud-drive")
    assert payload["plugin_manifest_path"].endswith(
        "plugins\\icloud-drive\\.codex-plugin\\plugin.json"
    )
    assert payload["marketplace_path"].endswith(".agents\\plugins\\marketplace.json")
    assert payload["marketplace_name"] == "iCloud Plugin Marketplace"
    assert payload["marketplace_add_command"].startswith("codex plugin marketplace add ")
    assert payload["plugin_add_command"] == (
        'codex plugin add "icloud-drive@iCloud Plugin Marketplace"'
    )
