from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from icloud_index_service.models.dedupe_group import DedupeGroup
from icloud_index_service.models.dedupe_group_item import DedupeGroupItem
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.manual_feedback_event import ManualFeedbackEvent
from icloud_index_service.services.file_mutation_service import (
    FileNamespace,
    _upsert_document_vault_note_record,
    resolve_namespace_root,
)
from icloud_index_service.services.vault_reconciliation import (
    collect_targeted_manual_feedback,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_known_labels() -> list[str]:
    try:
        from apps.classifier.category_manager import load_categories

        return [str(item).strip() for item in load_categories() if str(item).strip()]
    except Exception:
        return []


def sync_manual_feedback_events(
    session: Session,
    *,
    limit: int = 25,
) -> dict[str, object]:
    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
    rows = collect_targeted_manual_feedback(
        vault_root,
        known_labels=_load_known_labels(),
        folder_label_map_path=None,
        limit=limit,
    )
    created = 0
    unchanged = 0
    event_ids: list[str] = []

    for row in rows:
        note_path = Path(str(row["note_path"]))
        note_id = _upsert_document_vault_note_record(
            session,
            note_path=note_path,
            vault_root=vault_root,
        )
        if note_id is None:
            unchanged += 1
            continue

        source_path = str(row.get("source_path", "")).strip()
        source_file_record_id = session.scalar(
            select(FileRecord.id).where(FileRecord.path.ilike(f"%{Path(source_path).name}"))
        )
        observed_at = row.get("note_modified_at")
        if not isinstance(observed_at, datetime):
            observed_at = _utc_now()
        old_label = str(row.get("old_label", "")).strip()
        correct_label = str(row.get("correct_label", "")).strip()
        feedback_strength = str(row.get("feedback_strength", "strong")).strip() or "strong"
        event_type = "manual_override" if old_label and old_label != correct_label else "note_move"
        event_id = sha256(
            (
                f"{note_path.as_posix()}|{source_path}|{old_label}|{correct_label}|"
                f"{observed_at.isoformat()}"
            ).encode("utf-8")
        ).hexdigest()
        if session.scalar(
            select(ManualFeedbackEvent.id).where(ManualFeedbackEvent.event_id == event_id)
        ):
            unchanged += 1
            continue

        session.add(
            ManualFeedbackEvent(
                event_id=event_id,
                note_id=note_id,
                source_file_record_id=source_file_record_id,
                event_type=event_type,
                old_value_json=json.dumps({"label": old_label}, ensure_ascii=False),
                new_value_json=json.dumps({"label": correct_label}, ensure_ascii=False),
                observed_at=observed_at,
                feedback_strength=feedback_strength,
            )
        )
        created += 1
        event_ids.append(event_id)

    session.commit()
    return {
        "scanned": len(rows),
        "created": created,
        "unchanged": unchanged,
        "event_ids": event_ids,
    }


def reindex_document_vault_notes(
    session: Session,
    *,
    path_scope: str | None = None,
    limit: int = 25,
) -> dict[str, object]:
    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
    if not vault_root.exists() or not vault_root.is_dir():
        return {
            "scanned": 0,
            "indexed": 0,
            "path_scope": path_scope,
        }

    normalized_scope = str(path_scope or "").replace("\\", "/").strip("/")
    scope_root = vault_root / normalized_scope if normalized_scope else vault_root
    scope_root = scope_root.resolve()
    try:
        scope_root.relative_to(vault_root.resolve())
    except ValueError:
        return {
            "scanned": 0,
            "indexed": 0,
            "path_scope": path_scope,
        }

    if not scope_root.exists():
        return {
            "scanned": 0,
            "indexed": 0,
            "path_scope": path_scope,
        }

    indexed = 0
    scanned = 0
    for note_path in sorted(scope_root.rglob("*.md")):
        if any(part.startswith("_") for part in note_path.relative_to(vault_root).parts):
            continue
        scanned += 1
        if indexed < limit:
            _upsert_document_vault_note_record(
                session,
                note_path=note_path,
                vault_root=vault_root,
            )
            indexed += 1
    session.commit()
    return {
        "scanned": scanned,
        "indexed": indexed,
        "path_scope": normalized_scope or None,
    }


def _live_file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze_duplicate_groups(
    session: Session,
    *,
    namespaces: list[str],
    limit: int = 25,
) -> dict[str, object]:
    mirror_root = resolve_namespace_root(FileNamespace.GOOGLE1).parent
    active_namespaces = [item for item in namespaces if item in {"google1", "google2", "icloud"}]
    records = session.scalars(
        select(FileRecord).where(FileRecord.is_deleted.is_(False))
    ).all()

    candidates: dict[str, list[tuple[FileRecord, Path, str]]] = {}
    for record in records:
        cleaned = record.path.strip().lstrip("/")
        if not cleaned:
            continue
        namespace = cleaned.split("/", 1)[0]
        if namespace not in active_namespaces:
            continue
        if any(part.startswith("_") for part in cleaned.split("/")):
            continue
        live_path = (mirror_root / cleaned).resolve()
        if not live_path.exists() or not live_path.is_file():
            continue
        content_hash = _live_file_hash(live_path)
        key = f"{content_hash}:{record.size_bytes or 0}"
        candidates.setdefault(key, []).append((record, live_path, content_hash))

    created_groups: list[str] = []
    returned_groups: list[dict[str, object]] = []
    for fingerprint, items in sorted(candidates.items())[:limit]:
        if len(items) < 2:
            continue
        sorted_items = sorted(items, key=lambda item: (item[0].path.lower(), item[0].id))
        canonical_record, canonical_path, content_hash = sorted_items[0]
        dedupe_group_id = sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
        group = session.scalar(
            select(DedupeGroup).where(DedupeGroup.dedupe_group_id == dedupe_group_id)
        )
        evidence = {
            "content_hash": content_hash,
            "size_bytes": canonical_record.size_bytes,
            "members": [record.path for record, _, _ in sorted_items],
        }
        if group is None:
            group = DedupeGroup(
                dedupe_group_id=dedupe_group_id,
                group_fingerprint=fingerprint,
                status="candidate",
                canonical_item_path=canonical_record.path,
                canonical_file_record_id=canonical_record.id,
                duplicate_count=len(sorted_items) - 1,
                evidence_json=json.dumps(evidence, ensure_ascii=False),
                decision_notes="Generated by origin duplicate analysis dry-run.",
            )
            session.add(group)
            session.flush()
            for index, (record, _, _) in enumerate(sorted_items):
                session.add(
                    DedupeGroupItem(
                        dedupe_group_id=group.id,
                        file_record_id=record.id,
                        path_at_analysis_time=record.path,
                        content_hash=content_hash,
                        size_bytes=record.size_bytes,
                        similarity_score=1.0,
                        decision_role="canonical" if index == 0 else "duplicate",
                    )
                )
            created_groups.append(dedupe_group_id)
        else:
            group.updated_at = _utc_now()
        returned_groups.append(
            {
                "dedupe_group_id": dedupe_group_id,
                "status": group.status,
                "canonical_item_path": canonical_record.path,
                "duplicate_count": len(sorted_items) - 1,
                "members": [record.path for record, _, _ in sorted_items],
            }
        )

    session.commit()
    return {
        "created_groups": created_groups,
        "groups": returned_groups,
    }


def get_dedupe_group(session: Session, *, dedupe_group_id: str) -> dict[str, object] | None:
    group = session.scalar(
        select(DedupeGroup).where(DedupeGroup.dedupe_group_id == dedupe_group_id)
    )
    if group is None:
        return None
    items = session.scalars(
        select(DedupeGroupItem).where(DedupeGroupItem.dedupe_group_id == group.id)
    ).all()
    return {
        "dedupe_group_id": group.dedupe_group_id,
        "status": group.status,
        "canonical_item_path": group.canonical_item_path,
        "duplicate_count": group.duplicate_count,
        "evidence": json.loads(group.evidence_json) if group.evidence_json else {},
        "items": [
            {
                "file_record_id": item.file_record_id,
                "path_at_analysis_time": item.path_at_analysis_time,
                "content_hash": item.content_hash,
                "size_bytes": item.size_bytes,
                "similarity_score": item.similarity_score,
                "decision_role": item.decision_role,
            }
            for item in items
        ],
    }
