from __future__ import annotations

import json
import os
from enum import Enum
from hashlib import sha256
from pathlib import Path
from shutil import move
from uuid import uuid4

from apps.classifier.classify_to_obsidian import ensure_vault, write_obsidian_note
from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback


class FileMutationPolicyError(RuntimeError):
    pass


class FileNamespace(str, Enum):
    GOOGLE1 = "google1"
    GOOGLE2 = "google2"
    ICLOUD = "icloud"
    DOCUMENT_VAULT = "document_vault"


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


def _write_change_set_metadata(namespace: FileNamespace, change_set_id: str, payload: dict[str, object]) -> None:
    metadata_path = _change_set_metadata_path(namespace, change_set_id)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def delete_file_by_path(*, namespace: FileNamespace, relative_path: str, actor: str) -> dict[str, object]:
    live_path = resolve_live_path(
        namespace=namespace,
        relative_path=relative_path,
        allow_internal=False,
    )
    if not live_path.exists() or not live_path.is_file():
        raise FileMutationPolicyError("Live file does not exist.")

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
    return payload


def _import_legacy_internal_file(
    *,
    namespace: FileNamespace,
    relative_path: str,
    actor: str,
    legacy_source: str,
) -> dict[str, object]:
    live_path = resolve_live_path(
        namespace=namespace,
        relative_path=relative_path,
        allow_internal=True,
    )
    if not live_path.exists() or not live_path.is_file():
        raise FileMutationPolicyError("Legacy internal file does not exist.")

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
    return payload


def restore_change_set(*, change_set_id: str, actor: str) -> dict[str, object]:
    for namespace in FileNamespace:
        metadata_path = _change_set_metadata_path(namespace, change_set_id)
        if not metadata_path.exists():
            continue
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        live_path = resolve_live_path(
            namespace=namespace,
            relative_path=str(payload["original_relative_path"]),
            allow_internal=False,
        )
        live_path.parent.mkdir(parents=True, exist_ok=True)
        move(str(payload["backup_path"]), str(live_path))
        payload["status"] = "restored"
        payload["restored_by"] = actor
        _write_change_set_metadata(namespace, change_set_id, payload)
        return payload

    raise FileMutationPolicyError(f"Unknown change set: {change_set_id}")


def create_document_vault_note(
    *,
    relative_folder: str,
    visible_title: str,
    summary: str,
    canonical_source_path: str,
    attach_originals: bool = True,
) -> dict[str, object]:
    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
    ensure_vault(vault_root)
    source_path = Path(canonical_source_path).resolve()
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
    return {"note_path": str(note_path)}


def import_duplicate_quarantine_to_changes_backup(*, actor: str) -> dict[str, object]:
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

    return {
        "imported_files": imported_files,
        "change_sets_created": change_sets_created,
        "imported_artifacts": imported_artifacts,
    }
