from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from shutil import move
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.classifier.classify_to_obsidian import ensure_vault, write_obsidian_note
from icloud_index_service.models.change_set import ChangeSet
from icloud_index_service.models.change_set_item import ChangeSetItem
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.document_vault_note import DocumentVaultNote
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.classification_submission import (
    CLASSIFICATION_STATUS_COMPLETED,
    ClassifierSubmissionNotReadyError,
    PermanentClassifierSubmissionError,
    classify_file_on_mcp_fallback,
    get_classifier_mode,
    resolve_classification_file_path,
)
from icloud_index_service.services.file_access_service import resolve_file_source_path
from icloud_index_service.services.search_service import search_files
from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback


class FileMutationPolicyError(RuntimeError):
    pass


class FileNamespace(str, Enum):
    GOOGLE1 = "google1"
    GOOGLE2 = "google2"
    ICLOUD = "icloud"
    DOCUMENT_VAULT = "document_vault"


MAX_FALLBACK_BATCH_SIZE = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_namespace_root(namespace: FileNamespace) -> Path:
    if namespace == FileNamespace.DOCUMENT_VAULT:
        raw_root = (os.getenv("CLASSIFIER_VAULT_ROOT") or "").strip()
    else:
        mirror_root = Path((os.getenv("ICLOUD_MIRROR_ROOT") or "").strip()).resolve()
        return (mirror_root / namespace.value).resolve()

    return Path(raw_root).resolve()


def is_hidden_internal_path(path: Path, *, namespace_root: Path) -> bool:
    relative = path.resolve().relative_to(namespace_root.resolve())
    return any(part.startswith("_") for part in relative.parts)


def resolve_live_path(
    *,
    namespace: FileNamespace,
    relative_path: str,
    allow_internal: bool,
) -> Path:
    namespace_root = resolve_namespace_root(namespace)
    candidate = (namespace_root / relative_path).resolve()
    if candidate != namespace_root and namespace_root not in candidate.parents:
        raise FileMutationPolicyError("Resolved path escapes namespace root.")
    if not allow_internal and is_hidden_internal_path(candidate, namespace_root=namespace_root):
        raise FileMutationPolicyError(
            "Normal access to underscore-prefixed internal directories is not allowed."
        )
    return candidate


def _changes_backup_root(namespace: FileNamespace) -> Path:
    root = resolve_namespace_root(namespace) / "_CHANGES_BACKUP"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _change_set_metadata_path(namespace: FileNamespace, change_set_id: str) -> Path:
    return _changes_backup_root(namespace) / change_set_id / "change-set.json"


def _write_change_set_metadata(
    namespace: FileNamespace,
    change_set_id: str,
    payload: dict[str, object],
) -> None:
    metadata_path = _change_set_metadata_path(namespace, change_set_id)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _file_record_path(namespace: FileNamespace, relative_path: str) -> str:
    return f"/{namespace.value}/{relative_path.replace(chr(92), '/').strip('/')}"


def _find_file_record_id(
    session: Session | None,
    *,
    namespace: FileNamespace,
    relative_path: str,
) -> int | None:
    if session is None or namespace == FileNamespace.DOCUMENT_VAULT:
        return None
    record = session.scalar(
        select(FileRecord).where(FileRecord.path == _file_record_path(namespace, relative_path))
    )
    return record.id if record is not None else None


def _parse_frontmatter(note_text: str) -> dict[str, str]:
    lines = note_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    values: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed_value = raw_value.strip("'\"")
        if isinstance(parsed_value, str):
            values[key] = parsed_value
    return values


def _update_frontmatter_fields(note_text: str, updates: dict[str, str]) -> str:
    lines = note_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return note_text

    end_index = None
    field_indexes: dict[str, int] = {}
    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if stripped == "---":
            end_index = index
            break
        if ":" not in lines[index]:
            continue
        key = lines[index].split(":", 1)[0].strip()
        field_indexes[key] = index
    if end_index is None:
        return note_text

    insertion_index = end_index
    for key, value in updates.items():
        rendered = f"{key}: {json.dumps(value, ensure_ascii=False)}"
        if key in field_indexes:
            lines[field_indexes[key]] = rendered
        else:
            lines.insert(insertion_index, rendered)
            insertion_index += 1

    updated = "\n".join(lines)
    if note_text.endswith("\n"):
        updated += "\n"
    return updated


def _iter_note_paths_for_canonical_source(
    *,
    vault_root: Path,
    canonical_source_path: str,
) -> list[Path]:
    note_paths: list[Path] = []
    if not vault_root.exists():
        return note_paths

    for note_path in vault_root.rglob("*.md"):
        if any(part.startswith("_") for part in note_path.relative_to(vault_root).parts):
            continue
        metadata = _parse_frontmatter(note_path.read_text(encoding="utf-8", errors="replace"))
        if metadata.get("canonical_source_path") == canonical_source_path:
            note_paths.append(note_path)
    return note_paths


def _sync_note_source_state(
    *,
    session: Session | None,
    note_path: Path,
    vault_root: Path,
    status: str,
    change_set_id: str,
) -> int | None:
    note_text = note_path.read_text(encoding="utf-8", errors="replace")
    updated_text = _update_frontmatter_fields(
        note_text,
        {
            "source_status": status,
            "source_status_change_set_id": change_set_id,
        },
    )
    if updated_text != note_text:
        note_path.write_text(updated_text, encoding="utf-8")
    return _upsert_document_vault_note_record(
        session,
        note_path=note_path,
        vault_root=vault_root,
    )


def _upsert_document_vault_note_record(
    session: Session | None,
    *,
    note_path: Path,
    vault_root: Path,
) -> int | None:
    if session is None:
        return None

    note_text = note_path.read_text(encoding="utf-8", errors="replace")
    metadata = _parse_frontmatter(note_text)
    relative_path = note_path.resolve().relative_to(vault_root.resolve()).as_posix()
    visible_title = (
        metadata.get("last_seen_filename", "").strip() or note_path.stem
    )
    note_type = metadata.get("type", "").strip() or "classified-document"
    canonical_source_path = metadata.get("canonical_source_path", "").strip() or None
    source_file_record_id = None
    if canonical_source_path:
        mirror_root = Path((os.getenv("ICLOUD_MIRROR_ROOT") or "").strip()).resolve()
        for namespace in (FileNamespace.GOOGLE1, FileNamespace.GOOGLE2, FileNamespace.ICLOUD):
            namespace_root = (mirror_root / namespace.value).resolve()
            try:
                relative_source = Path(canonical_source_path).resolve().relative_to(namespace_root)
            except Exception:
                continue
            source_file_record_id = _find_file_record_id(
                session,
                namespace=namespace,
                relative_path=relative_source.as_posix(),
            )
            if source_file_record_id is not None:
                break

    note_record = session.scalar(
        select(DocumentVaultNote).where(DocumentVaultNote.relative_path == relative_path)
    )
    if note_record is None:
        note_record = DocumentVaultNote(
            relative_path=relative_path,
            visible_title=visible_title,
            note_type=note_type,
            frontmatter_json=json.dumps(metadata, ensure_ascii=False),
            canonical_source_path=canonical_source_path,
            source_file_record_id=source_file_record_id,
            attachment_mode=metadata.get("attachment_mode", "") or None,
            source_link=metadata.get("source_link", "") or None,
            primary_label=metadata.get("primary_label", "") or None,
            secondary_labels_json=json.dumps([], ensure_ascii=False),
            is_generated=note_type == "classified-document",
            is_deleted=False,
        )
        session.add(note_record)
    else:
        note_record.visible_title = visible_title
        note_record.note_type = note_type
        note_record.frontmatter_json = json.dumps(metadata, ensure_ascii=False)
        note_record.canonical_source_path = canonical_source_path
        note_record.source_file_record_id = source_file_record_id
        note_record.attachment_mode = metadata.get("attachment_mode", "") or None
        note_record.source_link = metadata.get("source_link", "") or None
        note_record.primary_label = metadata.get("primary_label", "") or None
        note_record.last_synced_at = _utc_now()
        note_record.last_observed_at = _utc_now()
        note_record.is_deleted = False
    session.flush()
    return note_record.id


def _persist_change_set(
    session: Session | None,
    *,
    payload: dict[str, object],
    item_type: str,
    file_record_id: int | None = None,
    document_note_record_id: int | None = None,
    content_hash_before: str | None = None,
    content_hash_after: str | None = None,
) -> None:
    if session is None:
        return

    change_set = session.scalar(
        select(ChangeSet).where(ChangeSet.change_set_id == str(payload["change_set_id"]))
    )
    if change_set is None:
        change_set = ChangeSet(
            change_set_id=str(payload["change_set_id"]),
            operation_type=str(payload["operation"]),
            namespace=str(payload["namespace"]),
            actor=str(payload["actor"]),
            applied_at=_utc_now(),
            completed_at=_utc_now(),
            status=str(payload["status"]),
            notes=str(payload.get("legacy_import") or payload.get("note_path") or "") or None,
            parent_change_set_id=str(payload.get("parent_change_set_id") or "") or None,
        )
        session.add(change_set)
        session.flush()
    else:
        change_set.status = str(payload["status"])
        change_set.completed_at = _utc_now()
        if payload.get("parent_change_set_id"):
            change_set.parent_change_set_id = str(payload["parent_change_set_id"])

    item = ChangeSetItem(
        change_set_id=change_set.id,
        item_type=item_type,
        namespace=str(payload["namespace"]),
        file_record_id=file_record_id,
        document_note_record_id=document_note_record_id,
        original_path=str(payload.get("original_relative_path") or payload.get("note_path") or "") or None,
        result_path=str(payload.get("result_path") or payload.get("note_path") or "") or None,
        backup_path=str(payload.get("backup_path") or "") or None,
        content_hash_before=content_hash_before,
        content_hash_after=content_hash_after,
        restore_status=str(payload.get("status") or "") or None,
        restore_error=str(payload.get("restore_error") or "") or None,
    )
    session.add(item)
    session.flush()


def get_change_set_record(session: Session, *, change_set_id: str) -> dict[str, object] | None:
    change_set = session.scalar(
        select(ChangeSet).where(ChangeSet.change_set_id == change_set_id)
    )
    if change_set is None:
        return None
    item_rows = session.scalars(
        select(ChangeSetItem).where(ChangeSetItem.change_set_id == change_set.id)
    ).all()
    return {
        "change_set_id": change_set.change_set_id,
        "operation_type": change_set.operation_type,
        "namespace": change_set.namespace,
        "actor": change_set.actor,
        "status": change_set.status,
        "created_at": change_set.created_at.isoformat(),
        "applied_at": change_set.applied_at.isoformat() if change_set.applied_at else None,
        "completed_at": change_set.completed_at.isoformat() if change_set.completed_at else None,
        "notes": change_set.notes,
        "parent_change_set_id": change_set.parent_change_set_id,
        "items": [
            {
                "item_type": row.item_type,
                "namespace": row.namespace,
                "file_record_id": row.file_record_id,
                "document_note_record_id": row.document_note_record_id,
                "original_path": row.original_path,
                "result_path": row.result_path,
                "backup_path": row.backup_path,
                "restore_status": row.restore_status,
                "restore_error": row.restore_error,
            }
            for row in item_rows
        ],
    }


def delete_file_by_path(
    *,
    namespace: FileNamespace,
    relative_path: str,
    actor: str,
    session: Session | None = None,
) -> dict[str, object]:
    live_path = resolve_live_path(
        namespace=namespace,
        relative_path=relative_path,
        allow_internal=False,
    )
    if not live_path.exists() or not live_path.is_file():
        raise FileMutationPolicyError("Live file does not exist.")

    file_record_id = _find_file_record_id(session, namespace=namespace, relative_path=relative_path)
    content_hash_before = sha256(live_path.read_bytes()).hexdigest()
    change_set_id = uuid4().hex
    backup_dir = _changes_backup_root(namespace) / change_set_id / "payload"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / live_path.name
    move(str(live_path), str(backup_path))

    payload = {
        "change_set_id": change_set_id,
        "namespace": namespace.value,
        "actor": actor,
        "operation": "delete",
        "original_relative_path": relative_path,
        "backup_path": str(backup_path),
        "status": "deleted",
    }
    _write_change_set_metadata(namespace, change_set_id, payload)

    if namespace != FileNamespace.DOCUMENT_VAULT:
        vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
        canonical_source_path = str(live_path)
        note_ids = [
            _sync_note_source_state(
                session=session,
                note_path=note_path,
                vault_root=vault_root,
                status="deleted",
                change_set_id=change_set_id,
            )
            for note_path in _iter_note_paths_for_canonical_source(
                vault_root=vault_root,
                canonical_source_path=canonical_source_path,
            )
        ]
        for note_id in note_ids:
            if note_id is not None:
                _persist_change_set(
                    session,
                    payload=payload,
                    item_type="document_vault_note",
                    document_note_record_id=note_id,
                )

    _persist_change_set(
        session,
        payload=payload,
        item_type="source_file",
        file_record_id=file_record_id,
        content_hash_before=content_hash_before,
    )
    if session is not None:
        session.commit()
    return payload


def _import_legacy_internal_file(
    *,
    namespace: FileNamespace,
    relative_path: str,
    actor: str,
    legacy_source: str,
    session: Session | None = None,
) -> dict[str, object]:
    live_path = resolve_live_path(
        namespace=namespace,
        relative_path=relative_path,
        allow_internal=True,
    )
    if not live_path.exists() or not live_path.is_file():
        raise FileMutationPolicyError("Legacy internal file does not exist.")

    file_record_id = _find_file_record_id(session, namespace=namespace, relative_path=relative_path)
    content_hash_before = sha256(live_path.read_bytes()).hexdigest()
    change_set_id = uuid4().hex
    backup_dir = _changes_backup_root(namespace) / change_set_id / "payload"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / live_path.name
    move(str(live_path), str(backup_path))
    payload = {
        "change_set_id": change_set_id,
        "namespace": namespace.value,
        "actor": actor,
        "operation": "legacy-import",
        "original_relative_path": relative_path,
        "backup_path": str(backup_path),
        "status": "imported",
        "legacy_import": legacy_source,
    }
    _write_change_set_metadata(namespace, change_set_id, payload)
    _persist_change_set(
        session,
        payload=payload,
        item_type="source_file",
        file_record_id=file_record_id,
        content_hash_before=content_hash_before,
    )
    return payload


def restore_change_set(
    *,
    change_set_id: str,
    actor: str,
    session: Session | None = None,
) -> dict[str, object]:
    for namespace in FileNamespace:
        metadata_path = _change_set_metadata_path(namespace, change_set_id)
        if not metadata_path.exists():
            continue
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        multi_items = payload.get("items")
        if isinstance(multi_items, list):
            restored_items: list[dict[str, object]] = []
            for entry in multi_items:
                entry_namespace = FileNamespace(str(entry["namespace"]))
                live_path = resolve_live_path(
                    namespace=entry_namespace,
                    relative_path=str(entry["original_relative_path"]),
                    allow_internal=False,
                )
                live_path.parent.mkdir(parents=True, exist_ok=True)
                move(str(entry["backup_path"]), str(live_path))

                file_record_id = _find_file_record_id(
                    session,
                    namespace=entry_namespace,
                    relative_path=str(entry["original_relative_path"]),
                )
                if entry_namespace != FileNamespace.DOCUMENT_VAULT:
                    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
                    note_ids = [
                        _sync_note_source_state(
                            session=session,
                            note_path=note_path,
                            vault_root=vault_root,
                            status="active",
                            change_set_id=change_set_id,
                        )
                        for note_path in _iter_note_paths_for_canonical_source(
                            vault_root=vault_root,
                            canonical_source_path=str(live_path),
                        )
                    ]
                    item_payload = {
                        "change_set_id": change_set_id,
                        "namespace": entry_namespace.value,
                        "actor": actor,
                        "operation": "restore",
                        "status": "restored",
                        "original_relative_path": str(entry["original_relative_path"]),
                        "backup_path": str(entry["backup_path"]),
                        "parent_change_set_id": change_set_id,
                    }
                    for note_id in note_ids:
                        if note_id is not None:
                            _persist_change_set(
                                session,
                                payload=item_payload,
                                item_type="document_vault_note",
                                document_note_record_id=note_id,
                            )
                else:
                    item_payload = {
                        "change_set_id": change_set_id,
                        "namespace": entry_namespace.value,
                        "actor": actor,
                        "operation": "restore",
                        "status": "restored",
                        "original_relative_path": str(entry["original_relative_path"]),
                        "backup_path": str(entry["backup_path"]),
                        "parent_change_set_id": change_set_id,
                    }
                _persist_change_set(
                    session,
                    payload=item_payload,
                    item_type="source_file",
                    file_record_id=file_record_id,
                    content_hash_after=sha256(live_path.read_bytes()).hexdigest(),
                )
                restored_items.append(
                    {
                        "namespace": entry_namespace.value,
                        "original_relative_path": str(entry["original_relative_path"]),
                        "backup_path": str(entry["backup_path"]),
                    }
                )

            payload["status"] = "restored"
            payload["restored_by"] = actor
            payload["parent_change_set_id"] = change_set_id
            payload["items"] = restored_items
            _write_change_set_metadata(namespace, change_set_id, payload)
            if session is not None:
                session.commit()
            return payload

        live_path = resolve_live_path(
            namespace=namespace,
            relative_path=str(payload["original_relative_path"]),
            allow_internal=False,
        )
        live_path.parent.mkdir(parents=True, exist_ok=True)
        move(str(payload["backup_path"]), str(live_path))
        payload["status"] = "restored"
        payload["restored_by"] = actor
        payload["parent_change_set_id"] = change_set_id
        _write_change_set_metadata(namespace, change_set_id, payload)

        file_record_id = _find_file_record_id(
            session,
            namespace=namespace,
            relative_path=str(payload["original_relative_path"]),
        )
        if namespace != FileNamespace.DOCUMENT_VAULT:
            vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
            note_ids = [
                _sync_note_source_state(
                    session=session,
                    note_path=note_path,
                    vault_root=vault_root,
                    status="active",
                    change_set_id=change_set_id,
                )
                for note_path in _iter_note_paths_for_canonical_source(
                    vault_root=vault_root,
                    canonical_source_path=str(live_path),
                )
            ]
            for note_id in note_ids:
                if note_id is not None:
                    _persist_change_set(
                        session,
                        payload=payload,
                        item_type="document_vault_note",
                        document_note_record_id=note_id,
                    )

        _persist_change_set(
            session,
            payload=payload,
            item_type="source_file",
            file_record_id=file_record_id,
            content_hash_after=sha256(live_path.read_bytes()).hexdigest(),
        )
        if session is not None:
            session.commit()
        return payload

    raise FileMutationPolicyError(f"Unknown change set: {change_set_id}")


def create_document_vault_note(
    *,
    relative_folder: str,
    visible_title: str,
    summary: str,
    file_id: int | None = None,
    canonical_source_path: str | None = None,
    attach_originals: bool = True,
    actor: str = "chatgpt-plugin",
    session: Session | None = None,
) -> dict[str, object]:
    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
    ensure_vault(vault_root)
    if file_id is not None:
        if session is None:
            raise FileMutationPolicyError("file_id-based note creation requires a database session.")
        # Prefer server-side source lookup so callers do not need to pass sensitive paths.
        resolved_source_path = resolve_file_source_path(session, file_id=file_id)
        if resolved_source_path is None:
            raise FileMutationPolicyError(f"Source file not found for file_id {file_id}.")
        source_path = resolved_source_path.resolve()
    elif canonical_source_path:
        source_path = Path(canonical_source_path).resolve()
    else:
        raise FileMutationPolicyError("Either file_id or canonical_source_path is required.")
    folder_parts = [part for part in relative_folder.replace("\\", "/").split("/") if part]
    primary_hint = folder_parts[-1] if folder_parts else "unknown"
    note_path = write_obsidian_note(
        vault=vault_root,
        source_path=source_path,
        file_hash=sha256(str(source_path).encode("utf-8")).hexdigest(),
        markdown=None,
        classification={
            "primary_label": primary_hint,
            "secondary_labels": [],
            "confidence": 1.0,
            "summary": summary,
            "reason": "Structured ChatGPT document_vault note creation.",
            "sensitive_flags": [],
            "recommended_action": "retain",
            "file_date_guess": "unknown",
            "language": "unknown",
        },
        attach_originals=attach_originals,
        canonical_source_path=str(source_path),
        last_seen_filename=visible_title,
        source_parser="manual-document-vault",
        heuristic_primary_hint=primary_hint,
        hybrid_live_source="chatgpt-plugin",
    )
    note_record_id = _upsert_document_vault_note_record(
        session,
        note_path=note_path,
        vault_root=vault_root,
    )

    change_set_id = uuid4().hex
    payload = {
        "change_set_id": change_set_id,
        "namespace": FileNamespace.DOCUMENT_VAULT.value,
        "actor": actor,
        "operation": "create",
        "note_path": str(note_path),
        "result_path": str(note_path),
        "status": "created",
    }
    _write_change_set_metadata(FileNamespace.DOCUMENT_VAULT, change_set_id, payload)
    _persist_change_set(
        session,
        payload=payload,
        item_type="document_vault_note",
        document_note_record_id=note_record_id,
    )

    feedback_path = vault_root / "_system" / "training" / "manual-note-feedback.jsonl"
    state_path = vault_root / "_system" / "training" / "manual-note-sync-state.json"
    sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=[],
        folder_label_map_path=None,
        limit=25,
    )
    if session is not None:
        session.commit()
    return {"note_path": str(note_path), "change_set_id": change_set_id}


def _resolve_document_vault_note_path(*, vault_root: Path, note_path_value: str) -> Path | None:
    cleaned = str(note_path_value or "").strip()
    if not cleaned:
        return None
    candidate = Path(cleaned)
    if not candidate.is_absolute():
        candidate = (vault_root / cleaned).resolve()
    else:
        candidate = candidate.resolve()
    if candidate != vault_root and vault_root not in candidate.parents:
        return None
    return candidate


def _find_active_document_vault_note_for_file(
    session: Session,
    *,
    file_id: int,
    vault_root: Path,
) -> tuple[DocumentVaultNote | None, Path | None]:
    note_record = session.scalar(
        select(DocumentVaultNote).where(
            DocumentVaultNote.source_file_record_id == file_id,
            DocumentVaultNote.is_deleted.is_(False),
        )
    )
    if note_record is None:
        state = session.scalar(
            select(ClassificationState).where(ClassificationState.file_id == file_id)
        )
        if state is None:
            return None, None
        note_path = _resolve_document_vault_note_path(
            vault_root=vault_root,
            note_path_value=state.classifier_note_path or "",
        )
        return None, note_path
    note_path = (vault_root / note_record.relative_path).resolve()
    return note_record, note_path


def _note_needs_review(
    *,
    note_path: Path | None,
    primary_label: str | None,
    confidence: float | None,
) -> bool:
    if note_path is not None and "02 Needs Review" in note_path.as_posix():
        return True
    if str(primary_label or "").strip() in {"unknown", "needs-review"}:
        return True
    if isinstance(confidence, (int, float)) and float(confidence) < 0.70:
        return True
    return False


def classify_file_and_create_document_vault_note_fallback(
    *,
    file_id: int,
    fallback_reason: str = "manual_fallback",
    force_reclassify: bool = False,
    summary_mode: str = "classifier",
    title_mode: str = "classifier",
    attach_originals: bool = True,
    idempotency_key: str | None = None,
    actor: str = "chatgpt-plugin",
    session: Session,
) -> dict[str, object]:
    del summary_mode, title_mode, idempotency_key
    file_record = session.get(FileRecord, file_id)
    if file_record is None:
        return {
            "status": "failed",
            "file_id": file_id,
            "note_path": None,
            "change_set_id": None,
            "fallback_reason": fallback_reason,
            "used_classifier": False,
            "classifier_invocation": "mcp_fallback_only",
            "classifier_status": "file-not-found",
            "primary_label": None,
            "confidence": None,
            "needs_review": False,
            "source_exists": False,
            "message": "Indexed file record was not found.",
        }

    source_exists = False
    try:
        source_path = resolve_classification_file_path(file_record)
        source_exists = source_path.exists() and source_path.is_file()
    except Exception:
        source_path = None

    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
    ensure_vault(vault_root)
    _, existing_note_path = _find_active_document_vault_note_for_file(
        session,
        file_id=file_id,
        vault_root=vault_root,
    )
    existing_state = session.scalar(
        select(ClassificationState).where(ClassificationState.file_id == file_id)
    )
    if existing_note_path is not None and existing_note_path.exists() and not force_reclassify:
        _upsert_document_vault_note_record(
            session,
            note_path=existing_note_path,
            vault_root=vault_root,
        )
        session.commit()
        return {
            "status": "existing",
            "file_id": file_id,
            "note_path": str(existing_note_path),
            "change_set_id": None,
            "fallback_reason": fallback_reason,
            "used_classifier": False,
            "classifier_invocation": "mcp_fallback_only",
            "classifier_status": (
                existing_state.submission_status if existing_state is not None else "not-run"
            ),
            "primary_label": existing_state.primary_label if existing_state is not None else None,
            "confidence": existing_state.confidence if existing_state is not None else None,
            "needs_review": _note_needs_review(
                note_path=existing_note_path,
                primary_label=existing_state.primary_label if existing_state is not None else None,
                confidence=existing_state.confidence if existing_state is not None else None,
            ),
            "source_exists": source_exists,
            "message": "Existing generated note already present; local classifier fallback was not invoked.",
        }

    try:
        state, used_classifier = classify_file_on_mcp_fallback(
            session,
            file_record=file_record,
            force_reclassify=force_reclassify,
        )
    except ClassifierSubmissionNotReadyError as exc:
        return {
            "status": "blocked",
            "file_id": file_id,
            "note_path": None,
            "change_set_id": None,
            "fallback_reason": fallback_reason,
            "used_classifier": False,
            "classifier_invocation": "mcp_fallback_only",
            "classifier_status": "blocked",
            "primary_label": None,
            "confidence": None,
            "needs_review": False,
            "source_exists": source_exists,
            "message": str(exc),
        }
    except PermanentClassifierSubmissionError as exc:
        return {
            "status": "failed",
            "file_id": file_id,
            "note_path": None,
            "change_set_id": None,
            "fallback_reason": fallback_reason,
            "used_classifier": False,
            "classifier_invocation": "mcp_fallback_only",
            "classifier_status": "rejected",
            "primary_label": None,
            "confidence": None,
            "needs_review": False,
            "source_exists": source_exists,
            "message": str(exc),
        }
    except RuntimeError as exc:
        return {
            "status": "failed",
            "file_id": file_id,
            "note_path": None,
            "change_set_id": None,
            "fallback_reason": fallback_reason,
            "used_classifier": False,
            "classifier_invocation": "mcp_fallback_only",
            "classifier_status": "failed",
            "primary_label": None,
            "confidence": None,
            "needs_review": False,
            "source_exists": source_exists,
            "message": str(exc),
        }

    note_path = _resolve_document_vault_note_path(
        vault_root=vault_root,
        note_path_value=state.classifier_note_path or "",
    )
    if note_path is None or not note_path.exists():
        return {
            "status": "failed",
            "file_id": file_id,
            "note_path": str(note_path) if note_path is not None else None,
            "change_set_id": None,
            "fallback_reason": fallback_reason,
            "used_classifier": used_classifier,
            "classifier_invocation": "mcp_fallback_only",
            "classifier_status": state.submission_status,
            "primary_label": state.primary_label,
            "confidence": state.confidence,
            "needs_review": _note_needs_review(
                note_path=note_path,
                primary_label=state.primary_label,
                confidence=state.confidence,
            ),
            "source_exists": source_exists,
            "message": "Classifier fallback completed without producing a readable note path in document_vault.",
        }

    note_record_id = _upsert_document_vault_note_record(
        session,
        note_path=note_path,
        vault_root=vault_root,
    )
    status = "updated" if existing_note_path is not None and existing_note_path.exists() else "created"
    change_set_id = uuid4().hex
    payload = {
        "change_set_id": change_set_id,
        "namespace": FileNamespace.DOCUMENT_VAULT.value,
        "actor": actor,
        "operation": "update" if status == "updated" else "create",
        "note_path": str(note_path),
        "result_path": str(note_path),
        "status": status,
        "source_file_record_id": file_id,
        "classifier_mode": get_classifier_mode(),
        "fallback_reason": fallback_reason,
    }
    _write_change_set_metadata(FileNamespace.DOCUMENT_VAULT, change_set_id, payload)
    _persist_change_set(
        session,
        payload=payload,
        item_type="document_vault_note",
        document_note_record_id=note_record_id,
    )
    feedback_path = vault_root / "_system" / "training" / "manual-note-feedback.jsonl"
    state_path = vault_root / "_system" / "training" / "manual-note-sync-state.json"
    sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=[],
        folder_label_map_path=None,
        limit=25,
    )
    session.commit()
    return {
        "status": status,
        "file_id": file_id,
        "note_path": str(note_path),
        "change_set_id": change_set_id,
        "fallback_reason": fallback_reason,
        "used_classifier": used_classifier,
        "classifier_invocation": "mcp_fallback_only",
        "classifier_status": state.submission_status,
        "primary_label": state.primary_label,
        "confidence": state.confidence,
        "needs_review": _note_needs_review(
            note_path=note_path,
            primary_label=state.primary_label,
            confidence=state.confidence,
        ),
        "source_exists": source_exists,
        "message": "Local classifier fallback wrote a document_vault note for the requested file.",
    }


def batch_classify_files_and_create_document_vault_notes_fallback(
    *,
    file_ids: list[int],
    fallback_reason: str = "manual_fallback",
    force_reclassify: bool = False,
    summary_mode: str = "classifier",
    title_mode: str = "classifier",
    attach_originals: bool = True,
    skip_existing: bool = False,
    limit: int | None = None,
    actor: str = "chatgpt-plugin",
    session: Session,
) -> dict[str, object]:
    capped_limit = min(max(limit or len(file_ids), 1), MAX_FALLBACK_BATCH_SIZE)
    unique_file_ids: list[int] = []
    seen: set[int] = set()
    for raw_file_id in file_ids:
        if raw_file_id in seen:
            continue
        seen.add(raw_file_id)
        unique_file_ids.append(raw_file_id)
    results = []
    for file_id in unique_file_ids[:capped_limit]:
        result = classify_file_and_create_document_vault_note_fallback(
            file_id=file_id,
            fallback_reason=fallback_reason,
            force_reclassify=force_reclassify,
            summary_mode=summary_mode,
            title_mode=title_mode,
            attach_originals=attach_originals,
            actor=actor,
            session=session,
        )
        if skip_existing and result["status"] == "existing":
            continue
        results.append(result)

    buckets = {key: [row for row in results if row["status"] == key] for key in ("created", "updated", "existing", "blocked", "failed")}
    return {
        **buckets,
        "count_created": len(buckets["created"]),
        "count_updated": len(buckets["updated"]),
        "count_existing": len(buckets["existing"]),
        "count_blocked": len(buckets["blocked"]),
        "count_failed": len(buckets["failed"]),
    }


def search_files_and_create_document_vault_notes_fallback(
    *,
    query: str,
    path_scope: str | None = None,
    namespace: str | None = None,
    limit: int = 10,
    fallback_reason: str = "manual_fallback",
    force_reclassify: bool = False,
    skip_existing: bool = False,
    summary_mode: str = "classifier",
    title_mode: str = "classifier",
    actor: str = "chatgpt-plugin",
    session: Session,
) -> dict[str, object]:
    matches = search_files(
        session,
        query=query,
        limit=min(max(limit, 1), MAX_FALLBACK_BATCH_SIZE),
        path_scope=path_scope,
    )
    if namespace:
        normalized_namespace = namespace.strip().strip("/")
        matches = [
            match for match in matches
            if str(match.get("path", "")).startswith(f"/{normalized_namespace}/")
        ]
    file_ids = [int(match["file_id"]) for match in matches if isinstance(match.get("file_id"), int)]
    batch_payload = batch_classify_files_and_create_document_vault_notes_fallback(
        file_ids=file_ids,
        fallback_reason=fallback_reason,
        force_reclassify=force_reclassify,
        summary_mode=summary_mode,
        title_mode=title_mode,
        attach_originals=True,
        skip_existing=skip_existing,
        limit=limit,
        actor=actor,
        session=session,
    )
    processed_count = (
        batch_payload["count_created"]
        + batch_payload["count_updated"]
        + batch_payload["count_existing"]
        + batch_payload["count_blocked"]
        + batch_payload["count_failed"]
    )
    return {
        "status": "ok",
        "matched_count": len(matches),
        "processed_count": processed_count,
        **batch_payload,
        "message": "Processed fallback document_vault note creation for the matching indexed files.",
    }


def import_duplicate_quarantine_to_changes_backup(
    *,
    actor: str,
    session: Session | None = None,
) -> dict[str, object]:
    imported_files = 0
    change_sets_created = 0
    imported_artifacts: list[dict[str, object]] = []

    for namespace in (
        FileNamespace.GOOGLE1,
        FileNamespace.GOOGLE2,
        FileNamespace.ICLOUD,
    ):
        namespace_root = resolve_namespace_root(namespace)
        quarantine_root = namespace_root / "_DUPLICATE_QUARANTINE"
        if not quarantine_root.exists():
            continue

        for source_path in quarantine_root.rglob("*"):
            if not source_path.is_file():
                continue

            relative_path = source_path.resolve().relative_to(namespace_root.resolve()).as_posix()
            payload = _import_legacy_internal_file(
                namespace=namespace,
                relative_path=relative_path,
                actor=actor,
                legacy_source="_DUPLICATE_QUARANTINE",
                session=session,
            )
            imported_files += 1
            change_sets_created += 1
            imported_artifacts.append(
                {
                    "namespace": namespace.value,
                    "source_path": str(source_path),
                    "change_set_id": payload["change_set_id"],
                }
            )
    if session is not None:
        session.commit()
    return {
        "imported_files": imported_files,
        "change_sets_created": change_sets_created,
        "imported_artifacts": imported_artifacts,
    }
