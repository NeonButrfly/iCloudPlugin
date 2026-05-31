from pathlib import Path

from icloud_index_service.services.product_readiness import (
    build_product_readiness_report,
    load_remote_mcp_tool_names,
)


def test_remote_mcp_submission_artifact_exposes_expected_tool_surface():
    repo_root = Path(__file__).resolve().parents[1]
    tool_names = load_remote_mcp_tool_names(repo_root)

    assert tool_names == {
        "search_icloud_files",
        "search_icloud_notes_and_files",
        "get_icloud_system_status",
        "get_icloud_product_readiness",
        "get_icloud_file",
        "get_icloud_file_excerpt",
        "get_icloud_note",
        "get_icloud_source_reference",
        "get_icloud_file_bundle",
        "refresh_icloud_index",
    }


def test_product_readiness_report_marks_repo_surface_ready_but_cloudflare_auth_blocked():
    repo_root = Path(__file__).resolve().parents[1]
    summary_payload = {
        "service_health": {"status": "ok"},
        "refresh_status": {"status": "running", "items_seen": 12},
        "provider_counts": {"icloud": 10, "google1": 3, "google2": 2},
        "classifier_health": {"ok": True},
        "classification_job_counts": {"completed": 7, "queued": 1},
        "classification_state_counts": {"completed": 5, "queued": 2},
        "generated_note_context_gaps": {
            "total_generated_notes": 11,
            "notes_missing_any_context": 2,
            "missing_context_with_matching_completed_state": 1,
            "missing_context_source_file_present": 2,
        },
        "vault_counts": {
            "attachments_files": 0,
            "classification_index_present": True,
            "home_note_present": True,
        },
    }

    report = build_product_readiness_report(
        repo_root=repo_root,
        summary_payload=summary_payload,
        cloudflare_api_token_present=False,
    )

    criteria = report["success_criteria"]
    assert criteria["aggregate_indexing_operational_and_observable"]["status"] == "met"
    assert criteria["full_ingestion_path_operational_and_observable"]["status"] == "met"
    assert criteria["manual_note_feedback_loop_operational_and_observable"]["status"] == "met"
    assert criteria["generated_notes_use_correct_canonical_linking"]["status"] == "met"
    assert criteria["obsidian_vault_behavior_is_sane_and_documented"]["status"] == "met"
    assert (
        criteria["cloudflare_remote_mcp_exists_and_is_the_intended_external_path"]["status"]
        == "met"
    )
    assert criteria["external_ai_can_access_note_and_source_layers"]["status"] == "met"
    assert criteria["auth_and_deployment_story_is_real"]["status"] == "blocked"
    assert report["overall"]["status"] == "incomplete"
    assert "auth_and_deployment_story_is_real" in report["overall"]["blocked_criteria"]


def test_product_readiness_report_blocks_runtime_checks_without_summary():
    repo_root = Path(__file__).resolve().parents[1]

    report = build_product_readiness_report(
        repo_root=repo_root,
        summary_payload=None,
        cloudflare_api_token_present=False,
    )

    criteria = report["success_criteria"]
    assert criteria["aggregate_indexing_operational_and_observable"]["status"] == "blocked"
    assert criteria["full_ingestion_path_operational_and_observable"]["status"] == "blocked"
    assert criteria["manual_note_feedback_loop_operational_and_observable"]["status"] == "blocked"
    assert criteria["generated_notes_use_correct_canonical_linking"]["status"] == "unknown"
    assert (
        criteria["cloudflare_remote_mcp_exists_and_is_the_intended_external_path"]["status"]
        == "met"
    )
