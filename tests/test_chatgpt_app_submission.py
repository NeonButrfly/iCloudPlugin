import json
from pathlib import Path


def test_remote_mcp_chatgpt_app_submission_matches_current_tool_surface():
    repo_root = Path(__file__).resolve().parents[1]
    submission_path = (
        repo_root / "cloudflare" / "remote-mcp" / "chatgpt-app-submission.json"
    )

    payload = json.loads(submission_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["app_info"]["display_name"] == "iCloudPlugin Remote MCP"
    assert payload["app_info"]["category"] == "PRODUCTIVITY"

    expected_tools = {
        "search_icloud_files",
        "search_icloud_notes_and_files",
        "get_icloud_system_status",
        "get_icloud_file",
        "get_icloud_file_excerpt",
        "get_icloud_note",
        "get_icloud_source_reference",
        "get_icloud_file_bundle",
        "refresh_icloud_index",
    }

    tools = payload["tools"]
    assert set(tools) == expected_tools

    for tool_name in expected_tools - {"refresh_icloud_index"}:
        annotations = tools[tool_name]["annotations"]
        assert annotations == {
            "readOnlyHint": True,
            "openWorldHint": False,
            "destructiveHint": False,
        }

    assert tools["refresh_icloud_index"]["annotations"] == {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
    }

    assert len(payload["test_cases"]) >= 5
    assert len(payload["negative_test_cases"]) >= 3
