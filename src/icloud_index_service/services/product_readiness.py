from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_REMOTE_MCP_TOOLS = (
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
)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    summary: str
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "summary": self.summary,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_ok_status(value: Any) -> bool:
    return str(value or "").strip().lower() == "ok"


def _has_counts(payload: Any) -> bool:
    return isinstance(payload, dict) and any(
        isinstance(count, int) and count >= 0 for count in payload.values()
    )


def _has_remote_mcp_tool_surface(tool_names: set[str]) -> tuple[bool, list[str]]:
    missing = [tool for tool in REQUIRED_REMOTE_MCP_TOOLS if tool not in tool_names]
    return not missing, missing


def load_remote_mcp_tool_names(repo_root: Path) -> set[str]:
    submission_path = repo_root / "cloudflare" / "remote-mcp" / "chatgpt-app-submission.json"
    if not submission_path.is_file():
        return set()

    try:
        payload = json.loads(submission_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()

    tools = payload.get("tools")
    if isinstance(tools, dict):
        return {
            str(name).strip()
            for name in tools.keys()
            if str(name).strip()
        }
    if isinstance(tools, list):
        tool_names: set[str] = set()
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip()
            if name:
                tool_names.add(name)
        return tool_names
    return set()


def collect_repo_surface_facts(repo_root: Path) -> dict[str, Any]:
    worker_dir = repo_root / "cloudflare" / "remote-mcp"
    plugin_server = repo_root / "src" / "icloud_plugin_mcp" / "server.py"
    worker_entrypoint = worker_dir / "src" / "index.ts"
    submission_path = worker_dir / "chatgpt-app-submission.json"
    deploy_helper = worker_dir / "scripts" / "deploy-and-verify.mjs"
    local_verify_helper = worker_dir / "scripts" / "dev-and-verify.mjs"
    smoke_verify_helper = worker_dir / "scripts" / "verify-mcp-tools.mjs"
    github_actions_workflow = (
        repo_root / ".github" / "workflows" / "remote-mcp-deploy.yml"
    )
    codex_readiness_helper = (
        repo_root / "deploy" / "roles" / "classifier" / "report_codex_arbiter_readiness.sh"
    )
    codex_smoke_helper = (
        repo_root / "deploy" / "roles" / "classifier" / "run_codex_arbiter_smoke.sh"
    )
    targeted_batch_helper = (
        repo_root / "deploy" / "roles" / "cloudsync" / "run_targeted_classification_batch.sh"
    )
    tool_names = load_remote_mcp_tool_names(repo_root)
    has_full_tool_surface, missing_tools = _has_remote_mcp_tool_surface(tool_names)

    return {
        "repo_root": str(repo_root),
        "remote_mcp_worker_present": worker_entrypoint.is_file(),
        "local_mcp_bridge_present": plugin_server.is_file(),
        "chatgpt_submission_artifact_present": submission_path.is_file(),
        "remote_mcp_deploy_helper_present": deploy_helper.is_file(),
        "remote_mcp_local_verify_helper_present": local_verify_helper.is_file(),
        "remote_mcp_smoke_verify_helper_present": smoke_verify_helper.is_file(),
        "remote_mcp_github_actions_workflow_present": github_actions_workflow.is_file(),
        "codex_readiness_helper_present": codex_readiness_helper.is_file(),
        "codex_smoke_helper_present": codex_smoke_helper.is_file(),
        "legacy_note_reconciliation_helper_present": targeted_batch_helper.is_file(),
        "remote_mcp_submission_tool_names": sorted(tool_names),
        "remote_mcp_has_full_required_tool_surface": has_full_tool_surface,
        "remote_mcp_missing_required_tools": missing_tools,
    }


def _evaluate_aggregate_indexing(summary: dict[str, Any]) -> ReadinessCheck:
    if not summary:
        return ReadinessCheck("blocked", "No authenticated status summary was provided.")

    service_health = _coerce_mapping(summary.get("service_health"))
    refresh_status = _coerce_mapping(summary.get("refresh_status"))
    provider_counts = _coerce_mapping(summary.get("provider_counts"))

    if not _is_ok_status(service_health.get("status")):
        return ReadinessCheck(
            "blocked",
            "Service health is not OK.",
            {"service_health": service_health},
        )

    refresh_state = str(refresh_status.get("status", "")).strip().lower()
    if refresh_state not in {"running", "idle", "completed"}:
        return ReadinessCheck(
            "blocked",
            "Refresh status is missing or not in a healthy state.",
            {"refresh_status": refresh_status},
        )

    if not _has_counts(provider_counts):
        return ReadinessCheck(
            "blocked",
            "Provider counts are missing, so aggregate mirror visibility is incomplete.",
            {"provider_counts": provider_counts},
        )

    return ReadinessCheck(
        "met",
        "Service health, refresh progress, and provider counts are all present.",
        {
            "refresh_status": refresh_status,
            "provider_counts": provider_counts,
        },
    )


def _evaluate_ingestion(summary: dict[str, Any]) -> ReadinessCheck:
    if not summary:
        return ReadinessCheck("blocked", "No authenticated status summary was provided.")

    classifier_health = _coerce_mapping(summary.get("classifier_health"))
    job_counts = _coerce_mapping(summary.get("classification_job_counts"))
    state_counts = _coerce_mapping(summary.get("classification_state_counts"))

    if classifier_health.get("ok") is not True:
        return ReadinessCheck(
            "blocked",
            "Classifier health is not OK.",
            {"classifier_health": classifier_health},
        )

    if not _has_counts(job_counts) or not _has_counts(state_counts):
        return ReadinessCheck(
            "blocked",
            "Classification queue/state counts are missing.",
            {
                "classification_job_counts": job_counts,
                "classification_state_counts": state_counts,
            },
        )

    return ReadinessCheck(
        "met",
        "Classifier health and queue/state observability are present.",
        {
            "classification_job_counts": job_counts,
            "classification_state_counts": state_counts,
        },
    )


def _evaluate_manual_feedback(summary: dict[str, Any]) -> ReadinessCheck:
    if not summary:
        return ReadinessCheck("blocked", "No authenticated status summary was provided.")

    gaps = _coerce_mapping(summary.get("generated_note_context_gaps"))
    if not gaps:
        return ReadinessCheck(
            "blocked",
            "Generated-note context-gap reporting is missing.",
        )

    required_keys = {
        "total_generated_notes",
        "notes_missing_any_context",
        "missing_context_with_matching_completed_state",
        "missing_context_source_file_present",
    }
    if not required_keys.issubset(gaps):
        return ReadinessCheck(
            "blocked",
            "Generated-note context-gap reporting is incomplete.",
            {"generated_note_context_gaps": gaps},
        )

    return ReadinessCheck(
        "met",
        "Generated-note context-gap reporting is available for manual-feedback repair work.",
        {"generated_note_context_gaps": gaps},
    )


def _evaluate_canonical_linking(summary: dict[str, Any]) -> ReadinessCheck:
    if not summary:
        return ReadinessCheck("unknown", "No authenticated status summary was provided.")

    vault_counts = _coerce_mapping(summary.get("vault_counts"))
    attachments_files = vault_counts.get("attachments_files")
    if not isinstance(attachments_files, int):
        return ReadinessCheck(
            "unknown",
            "Attachment copy counts are unavailable.",
            {"vault_counts": vault_counts},
        )

    if attachments_files != 0:
        return ReadinessCheck(
            "blocked",
            "Attachment copies are still present in the canonical vault surface.",
            {"vault_counts": vault_counts},
        )

    return ReadinessCheck(
        "met",
        "The canonical vault currently shows zero attachment-copy files.",
        {"vault_counts": vault_counts},
    )


def _evaluate_obsidian_vault(summary: dict[str, Any]) -> ReadinessCheck:
    if not summary:
        return ReadinessCheck("unknown", "No authenticated status summary was provided.")

    vault_counts = _coerce_mapping(summary.get("vault_counts"))
    if vault_counts.get("classification_index_present") is not True:
        return ReadinessCheck(
            "blocked",
            "Classification Index.md is not present in the vault view.",
            {"vault_counts": vault_counts},
        )

    if vault_counts.get("home_note_present") is not True:
        return ReadinessCheck(
            "blocked",
            "Home.md is not present in the vault view.",
            {"vault_counts": vault_counts},
        )

    return ReadinessCheck(
        "met",
        "The canonical vault exposes the expected top-level navigation notes.",
        {"vault_counts": vault_counts},
    )


def _evaluate_remote_mcp_surface(repo_facts: dict[str, Any]) -> ReadinessCheck:
    required_flags = (
        "remote_mcp_worker_present",
        "local_mcp_bridge_present",
        "chatgpt_submission_artifact_present",
        "remote_mcp_deploy_helper_present",
        "remote_mcp_smoke_verify_helper_present",
    )
    missing = [flag for flag in required_flags if repo_facts.get(flag) is not True]
    if missing:
        return ReadinessCheck(
            "blocked",
            "Remote MCP repo assets are incomplete.",
            {"missing_flags": missing},
        )

    if repo_facts.get("remote_mcp_has_full_required_tool_surface") is not True:
        return ReadinessCheck(
            "blocked",
            "The ChatGPT-facing remote MCP tool surface is incomplete.",
            {"missing_tools": repo_facts.get("remote_mcp_missing_required_tools", [])},
        )

    return ReadinessCheck(
        "met",
        "The repo contains the intended remote MCP worker, helpers, and full tool surface.",
        {
            "tool_names": repo_facts.get("remote_mcp_submission_tool_names", []),
        },
    )


def _evaluate_external_ai_access(repo_facts: dict[str, Any]) -> ReadinessCheck:
    tool_names = set(repo_facts.get("remote_mcp_submission_tool_names", []))
    required_subset = {
        "search_icloud_notes_and_files",
        "get_icloud_note",
        "get_icloud_source_reference",
        "get_icloud_file_bundle",
    }
    missing = sorted(required_subset - tool_names)
    if missing:
        return ReadinessCheck(
            "blocked",
            "The note/source retrieval tool surface is incomplete.",
            {"missing_tools": missing},
        )

    return ReadinessCheck(
        "met",
        "The repo exposes note-layer and source-layer retrieval tools for external AI use.",
        {"tool_names": sorted(required_subset)},
    )


def _evaluate_auth_and_deploy_story(
    repo_facts: dict[str, Any], *, cloudflare_api_token_present: bool
) -> ReadinessCheck:
    if not repo_facts.get("remote_mcp_deploy_helper_present"):
        return ReadinessCheck("blocked", "Remote MCP deploy helper is missing.")

    if repo_facts.get("remote_mcp_github_actions_workflow_present") is not True:
        return ReadinessCheck(
            "blocked",
            "Remote MCP GitHub-hosted deploy workflow is missing.",
        )

    if cloudflare_api_token_present:
        return ReadinessCheck(
            "in_progress",
            "Cloudflare deploy auth is present, but hosted proof still needs to be run.",
            {
                "github_actions_workflow_present": True,
            },
        )

    return ReadinessCheck(
        "blocked",
        "Cloudflare deploy auth is not present in this environment.",
        {
            "github_actions_workflow_present": True,
        },
    )


def _evaluate_docs_and_tracking(repo_facts: dict[str, Any]) -> ReadinessCheck:
    repo_root = Path(repo_facts["repo_root"])
    required_docs = [
        "docs/operations.md",
        "docs/chat-handoff.md",
        "docs/workspace-map.md",
        "docs/prompts/mcp.md",
    ]
    missing = [path for path in required_docs if not (repo_root / path).is_file()]
    if missing:
        return ReadinessCheck(
            "blocked",
            "Required operator/tracking docs are missing from the repo.",
            {"missing_docs": missing},
        )

    return ReadinessCheck(
        "met",
        "Core operator and prompt-tracking docs are present in the repo.",
    )


def build_product_readiness_report(
    *,
    repo_root: Path,
    summary_payload: dict[str, Any] | None = None,
    cloudflare_api_token_present: bool = False,
) -> dict[str, Any]:
    summary = _coerce_mapping(summary_payload)
    repo_facts = collect_repo_surface_facts(repo_root)

    criteria = {
        "aggregate_indexing_operational_and_observable": _evaluate_aggregate_indexing(summary),
        "full_ingestion_path_operational_and_observable": _evaluate_ingestion(summary),
        "manual_note_feedback_loop_operational_and_observable": _evaluate_manual_feedback(summary),
        "generated_notes_use_correct_canonical_linking": _evaluate_canonical_linking(summary),
        "obsidian_vault_behavior_is_sane_and_documented": _evaluate_obsidian_vault(summary),
        "cloudflare_remote_mcp_exists_and_is_the_intended_external_path": _evaluate_remote_mcp_surface(repo_facts),
        "external_ai_can_access_note_and_source_layers": _evaluate_external_ai_access(repo_facts),
        "auth_and_deployment_story_is_real": _evaluate_auth_and_deploy_story(
            repo_facts,
            cloudflare_api_token_present=cloudflare_api_token_present,
        ),
        "docs_issues_milestones_and_live_system_are_aligned": _evaluate_docs_and_tracking(repo_facts),
    }

    normalized_criteria = {name: check.to_payload() for name, check in criteria.items()}
    all_met = all(item["status"] == "met" for item in normalized_criteria.values())

    blocked_items = [
        name for name, item in normalized_criteria.items() if item["status"] == "blocked"
    ]
    overall_status = "complete" if all_met else "incomplete"
    overall_summary = (
        "All tracked product-readiness criteria are currently met."
        if all_met
        else (
            "Some product-readiness criteria remain blocked."
            if blocked_items
            else "Product readiness remains in progress."
        )
    )

    return {
        "repo_facts": repo_facts,
        "success_criteria": normalized_criteria,
        "overall": {
            "status": overall_status,
            "summary": overall_summary,
            "blocked_criteria": blocked_items,
        },
    }


def build_live_product_readiness_payload(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    status_summary: dict[str, Any],
    cloudflare_api_token_present: bool = False,
) -> dict[str, Any]:
    readiness_report = build_product_readiness_report(
        repo_root=repo_root,
        summary_payload=status_summary,
        cloudflare_api_token_present=cloudflare_api_token_present,
    )
    return {
        "generated_at": _utc_now_iso(),
        "status_summary": status_summary,
        "product_readiness": readiness_report,
    }
