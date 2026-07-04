from pathlib import Path

from icloud_index_service.services.product_readiness import (
    build_product_readiness_report,
    load_remote_mcp_hosted_proof,
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
        "get_icloud_change_set",
        "get_icloud_dedupe_job_status",
        "list_icloud_dedupe_groups",
        "get_icloud_dedupe_group",
        "get_icloud_file",
        "get_icloud_file_excerpt",
        "get_icloud_note",
        "get_icloud_source_reference",
        "get_icloud_file_bundle",
        "refresh_icloud_index",
        "pause_icloud_index",
        "resume_icloud_index",
        "create_document_vault_note",
        "classify_file_and_create_document_vault_note_fallback",
        "batch_classify_files_and_create_document_vault_notes_fallback",
        "search_files_and_create_document_vault_notes_fallback",
        "delete_icloud_file",
        "restore_icloud_change_set",
        "sync_icloud_manual_feedback_events",
        "analyze_icloud_duplicates",
        "start_icloud_dedupe_job",
        "continue_icloud_dedupe_job",
        "apply_icloud_dedupe_group",
    }


def test_remote_mcp_hosted_proof_artifact_is_present_and_structured():
    repo_root = Path(__file__).resolve().parents[1]
    proof = load_remote_mcp_hosted_proof(repo_root)

    assert proof["worker_base_url"] == "https://icloudplugin-remote-mcp.kaymayers9.workers.dev"
    assert proof["workflow_runs"]["deploy_and_verify"].endswith("/26731247268")
    assert set(proof["verified_probe_tools"]) == {
        "get_icloud_system_status",
        "get_icloud_product_readiness",
    }


def _build_minimal_repo_root(
    tmp_path: Path,
    *,
    include_hosted_proof: bool,
) -> Path:
    repo_root = tmp_path / "repo"
    required_files = [
        repo_root / "cloudflare" / "remote-mcp" / "src" / "index.ts",
        repo_root / "src" / "icloud_plugin_mcp" / "server.py",
        repo_root / "cloudflare" / "remote-mcp" / "scripts" / "deploy-and-verify.mjs",
        repo_root / "cloudflare" / "remote-mcp" / "scripts" / "verify-mcp-tools.mjs",
        repo_root / "cloudflare" / "remote-mcp" / "scripts" / "bootstrap-github-secrets.mjs",
        repo_root / "deploy" / "roles" / "classifier" / "report_codex_arbiter_readiness.sh",
        repo_root / "deploy" / "roles" / "classifier" / "run_codex_arbiter_smoke.sh",
        repo_root / "deploy" / "roles" / "cloudsync" / "run_targeted_classification_batch.sh",
        repo_root / ".github" / "workflows" / "remote-mcp-deploy.yml",
        repo_root / "docs" / "operations.md",
        repo_root / "docs" / "chat-handoff.md",
        repo_root / "docs" / "workspace-map.md",
        repo_root / "docs" / "prompts" / "mcp.md",
    ]
    for path in required_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub\n", encoding="utf-8")

    submission_path = repo_root / "cloudflare" / "remote-mcp" / "chatgpt-app-submission.json"
    submission_path.write_text(
        """{
  "tools": {
    "search_icloud_files": {},
    "search_icloud_notes_and_files": {},
    "get_icloud_system_status": {},
    "get_icloud_product_readiness": {},
    "get_icloud_change_set": {},
    "get_icloud_dedupe_job_status": {},
    "list_icloud_dedupe_groups": {},
    "get_icloud_dedupe_group": {},
    "get_icloud_file": {},
    "get_icloud_file_excerpt": {},
    "get_icloud_note": {},
    "get_icloud_source_reference": {},
    "get_icloud_file_bundle": {},
    "refresh_icloud_index": {},
    "pause_icloud_index": {},
    "resume_icloud_index": {},
    "create_document_vault_note": {},
    "classify_file_and_create_document_vault_note_fallback": {},
    "batch_classify_files_and_create_document_vault_notes_fallback": {},
    "search_files_and_create_document_vault_notes_fallback": {},
    "delete_icloud_file": {},
    "restore_icloud_change_set": {},
    "sync_icloud_manual_feedback_events": {},
    "analyze_icloud_duplicates": {},
    "start_icloud_dedupe_job": {},
    "continue_icloud_dedupe_job": {},
    "apply_icloud_dedupe_group": {}
  }
}
""",
        encoding="utf-8",
    )

    if include_hosted_proof:
        proof_path = repo_root / "cloudflare" / "remote-mcp" / "live-hosted-proof.json"
        proof_path.write_text(
            """{
  "worker_base_url": "https://example.workers.dev",
  "verified_probe_tools": ["get_icloud_system_status", "get_icloud_product_readiness"],
  "workflow_runs": {"deploy_and_verify": "https://example.invalid/run"}
}
""",
            encoding="utf-8",
        )

    return repo_root


def test_product_readiness_report_marks_repo_surface_ready_and_hosted_proof_met():
    repo_root = Path(__file__).resolve().parents[1]
    summary_payload = {
        "service_health": {"status": "ok"},
        "refresh_status": {"status": "running", "items_seen": 12},
        "provider_counts": {"icloud": 10, "google1": 3, "google2": 2},
        "classifier_health": {
            "ok": True,
            "classify_model": "qwen2.5:3b",
            "vision_model": "qwen2.5vl:3b",
        },
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
    assert criteria["classifier_runtime_still_uses_qwen_models"]["status"] == "met"
    assert criteria["manual_note_feedback_loop_operational_and_observable"]["status"] == "met"
    assert criteria["generated_notes_use_correct_canonical_linking"]["status"] == "met"
    assert criteria["obsidian_vault_behavior_is_sane_and_documented"]["status"] == "met"
    assert (
        criteria["cloudflare_remote_mcp_exists_and_is_the_intended_external_path"]["status"]
        == "met"
    )
    assert criteria["external_ai_can_access_note_and_source_layers"]["status"] == "met"
    assert criteria["auth_and_deployment_story_is_real"]["status"] == "met"
    assert report["repo_facts"]["remote_mcp_github_actions_workflow_present"] is True
    assert report["repo_facts"]["remote_mcp_github_secret_bootstrap_helper_present"] is True
    assert report["repo_facts"]["remote_mcp_hosted_proof_present"] is True


def test_product_readiness_report_blocks_auth_story_without_hosted_proof(tmp_path):
    repo_root = _build_minimal_repo_root(tmp_path, include_hosted_proof=False)
    summary_payload = {
        "service_health": {"status": "ok"},
        "refresh_status": {"status": "running", "items_seen": 12},
        "provider_counts": {"icloud": 10},
        "classifier_health": {
            "ok": True,
            "classify_model": "qwen2.5:3b",
            "vision_model": "qwen2.5vl:3b",
        },
        "classification_job_counts": {"completed": 7},
        "classification_state_counts": {"completed": 5},
        "generated_note_context_gaps": {
            "total_generated_notes": 11,
            "notes_missing_any_context": 0,
            "missing_context_with_matching_completed_state": 0,
            "missing_context_source_file_present": 0,
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

    criterion = report["success_criteria"]["auth_and_deployment_story_is_real"]
    assert criterion["status"] == "blocked"
    assert criterion["summary"] == "Cloudflare deploy auth is not present in this environment."


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
    assert criteria["classifier_runtime_still_uses_qwen_models"]["status"] == "blocked"
    assert criteria["manual_note_feedback_loop_operational_and_observable"]["status"] == "blocked"
    assert criteria["generated_notes_use_correct_canonical_linking"]["status"] == "unknown"
    assert (
        criteria["cloudflare_remote_mcp_exists_and_is_the_intended_external_path"]["status"]
        == "met"
    )


def test_product_readiness_report_blocks_when_classifier_models_are_not_qwen():
    repo_root = Path(__file__).resolve().parents[1]
    summary_payload = {
        "service_health": {"status": "ok"},
        "refresh_status": {"status": "running", "items_seen": 12},
        "provider_counts": {"icloud": 10},
        "classifier_health": {
            "ok": True,
            "classify_model": "llama3.2:3b",
            "vision_model": "qwen2.5vl:3b",
        },
        "classification_job_counts": {"completed": 7},
        "classification_state_counts": {"completed": 5},
        "generated_note_context_gaps": {
            "total_generated_notes": 11,
            "notes_missing_any_context": 0,
            "missing_context_with_matching_completed_state": 0,
            "missing_context_source_file_present": 0,
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

    criterion = report["success_criteria"]["classifier_runtime_still_uses_qwen_models"]
    assert criterion["status"] == "blocked"
    assert criterion["details"] == {
        "classify_model": "llama3.2:3b",
        "vision_model": "qwen2.5vl:3b",
    }


def test_product_readiness_report_blocks_when_qwen_models_are_not_loaded():
    repo_root = Path(__file__).resolve().parents[1]
    summary_payload = {
        "service_health": {"status": "ok"},
        "refresh_status": {"status": "running", "items_seen": 12},
        "provider_counts": {"icloud": 10},
        "classifier_health": {
            "ok": False,
            "classify_model": "qwen2.5:3b",
            "vision_model": "qwen2.5vl:3b",
            "available_models": [],
            "missing_models": ["qwen2.5:3b", "qwen2.5vl:3b"],
            "required_models_present": False,
        },
        "classification_job_counts": {"completed": 7},
        "classification_state_counts": {"completed": 5},
        "generated_note_context_gaps": {
            "total_generated_notes": 11,
            "notes_missing_any_context": 0,
            "missing_context_with_matching_completed_state": 0,
            "missing_context_source_file_present": 0,
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

    criterion = report["success_criteria"]["classifier_runtime_still_uses_qwen_models"]
    assert criterion["status"] == "blocked"
    assert criterion["details"] == {
        "classify_model": "qwen2.5:3b",
        "vision_model": "qwen2.5vl:3b",
        "available_models": [],
        "missing_models": ["qwen2.5:3b", "qwen2.5vl:3b"],
        "required_models_present": False,
    }
