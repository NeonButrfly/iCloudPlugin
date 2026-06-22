from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from icloud_index_service.models.classification_job import ClassificationJob
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.job_runner import get_refresh_status_snapshot
from icloud_index_service.services.vault_reconciliation import _iter_generated_notes

DEFAULT_CLASSIFIER_HEALTH_TIMEOUT_SECONDS = 5.0
DEFAULT_CLASSIFIER_HEALTH_URL = "http://127.0.0.1:4319/health"
DEFAULT_VAULT_ROOT = "/srv/cloud-vault/document-vault"
DEFAULT_CLOUD_VAULT_SYNC_STATUS_PATH = "/srv/cloud-vault/logs/cloud-vault-sync-status.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_classifier_health_url() -> str:
    configured_url = (os.getenv("CLASSIFIER_API_URL") or "").strip()
    if configured_url:
        return f"{configured_url.rstrip('/')}/health"
    return DEFAULT_CLASSIFIER_HEALTH_URL


def _resolve_vault_root() -> Path:
    raw_value = (os.getenv("CLASSIFIER_VAULT_ROOT") or DEFAULT_VAULT_ROOT).strip()
    return Path(raw_value)


def _resolve_cloud_vault_sync_status_path() -> Path:
    raw_value = (
        os.getenv("CLOUD_VAULT_SYNC_STATUS_PATH") or DEFAULT_CLOUD_VAULT_SYNC_STATUS_PATH
    ).strip()
    return Path(raw_value)


def _resolve_mirror_root() -> Path:
    raw_value = (os.getenv("ICLOUD_MIRROR_ROOT") or "/srv/cloud-vault/mirrors").strip()
    return Path(raw_value)


def _count_values(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _candidate_canonical_mirror_roots(mirror_root: Path) -> list[PurePosixPath]:
    candidates: list[PurePosixPath] = []
    for raw_value in (
        os.getenv("ICLOUD_MIRROR_ROOT", ""),
        str(mirror_root),
        "/srv/cloud-vault/mirrors",
        "/mnt/cloud-vault/mirrors",
    ):
        cleaned = str(raw_value).strip().replace("\\", "/").rstrip("/")
        if not cleaned:
            continue
        candidate = PurePosixPath(cleaned)
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _canonical_source_to_file_record_path(
    canonical_source_path: str,
    *,
    mirror_root: Path,
) -> str:
    cleaned = str(canonical_source_path or "").strip()
    if not cleaned:
        return ""

    try:
        relative_path = Path(cleaned).resolve().relative_to(mirror_root.resolve())
    except (OSError, ValueError):
        normalized = cleaned.replace("\\", "/")
        source_posix = PurePosixPath(normalized)
        for canonical_root in _candidate_canonical_mirror_roots(mirror_root):
            try:
                relative_posix = source_posix.relative_to(canonical_root)
            except ValueError:
                continue
            relative_parts = [part for part in relative_posix.parts if part]
            if relative_parts:
                return "/" + "/".join(relative_parts)
        return ""

    relative_parts = [part for part in relative_path.parts if part]
    if not relative_parts:
        return ""
    return "/" + "/".join(relative_parts)


def _resolve_source_exists(
    canonical_source_path: str,
    *,
    mirror_root: Path,
) -> bool:
    cleaned = str(canonical_source_path or "").strip()
    if not cleaned:
        return False
    candidate = Path(cleaned)
    if candidate.exists() and candidate.is_file():
        return True
    file_record_path = _canonical_source_to_file_record_path(cleaned, mirror_root=mirror_root)
    if not file_record_path:
        return False
    mirror_candidate = (mirror_root / file_record_path.lstrip("/")).resolve()
    return mirror_candidate.exists() and mirror_candidate.is_file()


def _count_vault_files(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file())


def collect_vault_counts(*, vault_root: Path | None = None) -> dict[str, Any]:
    active_vault_root = (vault_root or _resolve_vault_root()).resolve()
    return {
        "vault_root": str(active_vault_root),
        "vault_root_exists": active_vault_root.exists() and active_vault_root.is_dir(),
        "classified_files": _count_vault_files(active_vault_root / "01 Classified"),
        "needs_review_files": _count_vault_files(active_vault_root / "02 Needs Review"),
        "attachments_files": _count_vault_files(active_vault_root / "90 Attachments"),
        "extracted_markdown_files": _count_vault_files(active_vault_root / "_system/extracted-markdown"),
        "classification_index_present": (active_vault_root / "Classification Index.md").is_file(),
        "home_note_present": (active_vault_root / "Home.md").is_file(),
    }


def collect_generated_note_context_gaps(
    session: Session,
    *,
    vault_root: Path | None = None,
    mirror_root: Path | None = None,
) -> dict[str, Any]:
    active_vault_root = (vault_root or _resolve_vault_root()).resolve()
    active_mirror_root = (mirror_root or _resolve_mirror_root()).resolve()

    state_rows = session.execute(
        select(FileRecord.path, ClassificationState.submission_status).join(
            ClassificationState,
            ClassificationState.file_id == FileRecord.id,
        )
    ).all()
    statuses_by_path: dict[str, list[str]] = {}
    for file_path, submission_status in state_rows:
        if not isinstance(file_path, str) or not isinstance(submission_status, str):
            continue
        statuses_by_path.setdefault(file_path, []).append(submission_status)

    summary = {
        "vault_root": str(active_vault_root),
        "mirror_root": str(active_mirror_root),
        "total_generated_notes": 0,
        "notes_missing_any_context": 0,
        "notes_missing_source_parser": 0,
        "notes_missing_heuristic_primary_hint": 0,
        "notes_missing_hybrid_live_source": 0,
        "missing_context_with_matching_completed_state": 0,
        "missing_context_with_matching_queued_state": 0,
        "missing_context_with_matching_other_state": 0,
        "missing_context_without_matching_state": 0,
        "missing_context_source_file_present": 0,
        "missing_context_source_file_missing": 0,
    }

    if not active_vault_root.exists() or not active_vault_root.is_dir():
        return summary

    for _, metadata in _iter_generated_notes(active_vault_root):
        summary["total_generated_notes"] += 1
        missing_parser = not str(metadata.get("source_parser", "")).strip()
        missing_heuristic = not str(metadata.get("heuristic_primary_hint", "")).strip()
        missing_live_source = not str(metadata.get("hybrid_live_source", "")).strip()
        if not (missing_parser or missing_heuristic or missing_live_source):
            continue

        summary["notes_missing_any_context"] += 1
        if missing_parser:
            summary["notes_missing_source_parser"] += 1
        if missing_heuristic:
            summary["notes_missing_heuristic_primary_hint"] += 1
        if missing_live_source:
            summary["notes_missing_hybrid_live_source"] += 1

        canonical_source_path = str(metadata.get("canonical_source_path", "")).strip()
        if _resolve_source_exists(canonical_source_path, mirror_root=active_mirror_root):
            summary["missing_context_source_file_present"] += 1
        else:
            summary["missing_context_source_file_missing"] += 1

        file_record_path = _canonical_source_to_file_record_path(
            canonical_source_path,
            mirror_root=active_mirror_root,
        )
        matching_statuses = statuses_by_path.get(file_record_path, [])
        if any(status == "completed" for status in matching_statuses):
            summary["missing_context_with_matching_completed_state"] += 1
        elif any(status == "queued" for status in matching_statuses):
            summary["missing_context_with_matching_queued_state"] += 1
        elif matching_statuses:
            summary["missing_context_with_matching_other_state"] += 1
        else:
            summary["missing_context_without_matching_state"] += 1

    return summary


def collect_cloud_vault_sync_status(
    *, sync_status_path: Path | None = None
) -> dict[str, Any]:
    active_path = (sync_status_path or _resolve_cloud_vault_sync_status_path()).resolve()
    if not active_path.exists() or not active_path.is_file():
        return {
            "status_file": str(active_path),
            "status_file_present": False,
            "overall_status": "unknown",
        }

    try:
        payload = json.loads(active_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status_file": str(active_path),
            "status_file_present": True,
            "overall_status": "unknown",
            "error": "sync-status-invalid",
            "detail": str(exc),
        }

    if not isinstance(payload, dict):
        return {
            "status_file": str(active_path),
            "status_file_present": True,
            "overall_status": "unknown",
            "error": "sync-status-non-object",
        }

    return {
        "status_file": str(active_path),
        "status_file_present": True,
        **payload,
    }


def collect_classification_job_counts(session: Session) -> dict[str, int]:
    statuses = session.scalars(select(ClassificationJob.status)).all()
    return _count_values([status for status in statuses if isinstance(status, str)])


def collect_classification_state_counts(session: Session) -> dict[str, int]:
    statuses = session.scalars(select(ClassificationState.submission_status)).all()
    return _count_values([status for status in statuses if isinstance(status, str)])


def collect_provider_counts(session: Session) -> dict[str, int]:
    paths = session.scalars(
        select(FileRecord.path).where(FileRecord.is_deleted.is_(False))
    ).all()
    providers: list[str] = []
    for raw_path in paths:
        if not isinstance(raw_path, str):
            continue
        cleaned = raw_path.strip().lstrip("/")
        if not cleaned:
            continue
        provider = cleaned.split("/", 1)[0].strip()
        if provider:
            providers.append(provider)
    return _count_values(providers)


def fetch_classifier_health() -> dict[str, Any]:
    token = (os.getenv("CLASSIFIER_API_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "error": "classifier-api-token-missing"}

    url = _resolve_classifier_health_url()
    try:
        with httpx.Client(
            timeout=DEFAULT_CLASSIFIER_HEALTH_TIMEOUT_SECONDS,
            trust_env=False,
        ) as client:
            response = client.get(url, headers={"X-API-Key": token})
            response.raise_for_status()
    except OSError as exc:
        return {
            "ok": False,
            "error": "classifier-health-client-init-failed",
            "detail": str(exc),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "error": "classifier-health-request-failed",
            "detail": str(exc),
        }

    try:
        payload = response.json()
    except ValueError as exc:
        return {
            "ok": False,
            "error": "classifier-health-invalid-json",
            "detail": str(exc),
        }

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error": "classifier-health-non-object-payload",
        }
    return payload


def build_status_summary(
    session: Session,
    *,
    service_health: dict[str, Any],
    auth_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "service_health": service_health,
        "auth_status": auth_status,
        "refresh_status": get_refresh_status_snapshot(session),
        "classifier_health": fetch_classifier_health(),
        "classification_job_counts": collect_classification_job_counts(session),
        "classification_state_counts": collect_classification_state_counts(session),
        "provider_counts": collect_provider_counts(session),
        "vault_counts": collect_vault_counts(),
        "generated_note_context_gaps": collect_generated_note_context_gaps(session),
        "cloud_vault_sync": collect_cloud_vault_sync_status(),
    }
