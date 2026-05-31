from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.search_service import summarize_text
from icloud_index_service.services.vault_reconciliation import _build_canonical_source_link

MAX_NOTE_CONTENT_CHARS = 40_000


def _resolve_vault_root() -> Path | None:
    raw_value = (os.getenv("CLASSIFIER_VAULT_ROOT") or "").strip()
    if not raw_value:
        return None
    vault_root = Path(raw_value).resolve()
    if not vault_root.exists() or not vault_root.is_dir():
        return None
    return vault_root


def _resolve_mirror_root() -> Path | None:
    raw_value = (os.getenv("ICLOUD_MIRROR_ROOT") or "").strip()
    if not raw_value:
        return None
    mirror_root = Path(raw_value).resolve()
    if not mirror_root.exists() or not mirror_root.is_dir():
        return None
    return mirror_root


def _parse_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}

    values: dict[str, Any] = {}
    for line in lines[1:end_index]:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value_text = raw_value.strip()
        try:
            values[key] = json.loads(value_text)
        except json.JSONDecodeError:
            values[key] = value_text.strip("'\"")
    return values


def _load_manifest_record(state: ClassificationState | None) -> dict[str, Any]:
    for raw_value in (
        state.classifier_manifest_record if state is not None else None,
        state.response_payload_json if state is not None else None,
    ):
        if not raw_value:
            continue
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            record = parsed.get("record")
            if isinstance(record, dict):
                return record
            return parsed
    return {}


def _resolve_note_path(note_reference: str | None, vault_root: Path | None) -> Path | None:
    if vault_root is None:
        return None
    cleaned_reference = str(note_reference or "").strip()
    if not cleaned_reference:
        return None

    if cleaned_reference.startswith("/vault/"):
        cleaned_reference = cleaned_reference[len("/vault/") :]

    candidate = Path(cleaned_reference)
    if candidate.is_absolute():
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
        return None

    resolved = (vault_root / cleaned_reference.lstrip("/")).resolve()
    try:
        resolved.relative_to(vault_root.resolve())
    except ValueError:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _resolve_canonical_source_path(
    *,
    file_record: FileRecord,
    state: ClassificationState | None,
    note_metadata: dict[str, Any],
    manifest_record: dict[str, Any],
) -> str:
    candidate_values: list[str] = []
    for candidate in (
        note_metadata.get("canonical_source_path"),
        manifest_record.get("canonical_source_path"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            candidate_values.append(candidate.strip())

    for candidate in candidate_values:
        try:
            candidate_path = Path(candidate).resolve()
        except Exception:
            continue
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)

    if candidate_values:
        return candidate_values[0]

    mirror_root = _resolve_mirror_root()
    if mirror_root is None:
        return ""
    return str((mirror_root / file_record.path.lstrip("/")).resolve())


def _base_file_row(
    session: Session,
    *,
    file_id: int,
) -> tuple[FileRecord, ClassificationState | None] | None:
    statement = (
        select(FileRecord, ClassificationState)
        .outerjoin(ClassificationState, ClassificationState.file_id == FileRecord.id)
        .where(FileRecord.id == file_id)
        .where(FileRecord.is_deleted.is_(False))
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    return row


def get_file_note_details(
    session: Session,
    *,
    file_id: int,
    max_chars: int = MAX_NOTE_CONTENT_CHARS,
) -> dict[str, Any] | None:
    row = _base_file_row(session, file_id=file_id)
    if row is None:
        return None

    file_record, state = row
    vault_root = _resolve_vault_root()
    note_reference = state.classifier_note_path if state is not None else None
    note_path = _resolve_note_path(note_reference, vault_root)
    note_text = note_path.read_text(encoding="utf-8", errors="replace") if note_path else ""
    note_metadata = _parse_frontmatter(note_text) if note_text else {}
    manifest_record = _load_manifest_record(state)
    canonical_source_path = _resolve_canonical_source_path(
        file_record=file_record,
        state=state,
        note_metadata=note_metadata,
        manifest_record=manifest_record,
    )
    source_link = ""
    raw_source_link = note_metadata.get("source_link") or manifest_record.get("source_link")
    if isinstance(raw_source_link, str) and raw_source_link.strip():
        source_link = raw_source_link.strip()
    elif canonical_source_path:
        source_link = _build_canonical_source_link(canonical_source_path, file_record.name)

    content_length = len(note_text)
    content_text = note_text[:max_chars]
    return {
        "file_id": file_record.id,
        "name": file_record.name,
        "path": file_record.path,
        "primary_label": state.primary_label if state is not None else None,
        "note_available": note_path is not None,
        "note_reference": note_reference,
        "note_relative_path": (
            note_path.resolve().relative_to(vault_root.resolve()).as_posix()
            if note_path is not None and vault_root is not None
            else None
        ),
        "note_content": content_text,
        "note_length": content_length,
        "note_truncated": content_length > max_chars,
        "note_excerpt": summarize_text(note_text, 280) if note_text else "",
        "canonical_source_path": canonical_source_path or None,
        "source_link": source_link or None,
        "attachment_mode": note_metadata.get("attachment_mode") or manifest_record.get("attachment_mode"),
    }


def get_file_source_details(
    session: Session,
    *,
    file_id: int,
) -> dict[str, Any] | None:
    row = _base_file_row(session, file_id=file_id)
    if row is None:
        return None

    file_record, state = row
    manifest_record = _load_manifest_record(state)
    note_details = get_file_note_details(session, file_id=file_id, max_chars=MAX_NOTE_CONTENT_CHARS)
    canonical_source_path = ""
    if note_details is not None and isinstance(note_details.get("canonical_source_path"), str):
        canonical_source_path = str(note_details["canonical_source_path"] or "")
    if not canonical_source_path:
        canonical_source_path = _resolve_canonical_source_path(
            file_record=file_record,
            state=state,
            note_metadata={},
            manifest_record=manifest_record,
        )

    source_path = Path(canonical_source_path).resolve() if canonical_source_path else None
    source_exists = bool(source_path and source_path.exists() and source_path.is_file())
    source_link = ""
    for candidate in (
        note_details.get("source_link") if note_details is not None else None,
        manifest_record.get("source_link"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            source_link = candidate.strip()
            break
    if not source_link and canonical_source_path:
        source_link = _build_canonical_source_link(canonical_source_path, file_record.name)

    attachment_mode = ""
    for candidate in (
        note_details.get("attachment_mode") if note_details is not None else None,
        manifest_record.get("attachment_mode"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            attachment_mode = candidate.strip()
            break

    return {
        "file_id": file_record.id,
        "name": file_record.name,
        "path": file_record.path,
        "mime_type": file_record.mime_type,
        "canonical_source_path": canonical_source_path or None,
        "source_exists": source_exists,
        "source_size_bytes": source_path.stat().st_size if source_exists and source_path is not None else None,
        "source_link": source_link or None,
        "attachment_mode": attachment_mode or None,
        "download_path": f"/files/{file_record.id}/source/download" if source_exists else None,
    }


def resolve_file_source_path(session: Session, *, file_id: int) -> Path | None:
    details = get_file_source_details(session, file_id=file_id)
    canonical_source_path = str(details.get("canonical_source_path") or "") if details is not None else ""
    if not canonical_source_path:
        return None
    resolved = Path(canonical_source_path).resolve()
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved
