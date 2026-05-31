from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from icloud_index_service.models.classification_job import ClassificationJob
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.job_runner import get_refresh_status_snapshot

DEFAULT_CLASSIFIER_HEALTH_TIMEOUT_SECONDS = 5.0
DEFAULT_CLASSIFIER_HEALTH_URL = "http://127.0.0.1:4319/health"
DEFAULT_VAULT_ROOT = "/srv/cloud-vault/document-vault"


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


def _count_values(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


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
        with httpx.Client(timeout=DEFAULT_CLASSIFIER_HEALTH_TIMEOUT_SECONDS) as client:
            response = client.get(url, headers={"X-API-Key": token})
            response.raise_for_status()
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
    }
