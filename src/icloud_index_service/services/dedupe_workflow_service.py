from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from shutil import move
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from icloud_index_service.models.change_set import ChangeSet
from icloud_index_service.models.dedupe_group import DedupeGroup
from icloud_index_service.models.dedupe_group_item import DedupeGroupItem
from icloud_index_service.models.dedupe_job import DedupeJob
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.file_mutation_service import (
    FileMutationPolicyError,
    FileNamespace,
    _changes_backup_root,
    _find_file_record_id,
    _persist_change_set,
    _sync_note_source_state,
    _write_change_set_metadata,
    _iter_note_paths_for_canonical_source,
    resolve_live_path,
    resolve_namespace_root,
)

DEDUPE_STATUS_QUEUED = "queued"
DEDUPE_STATUS_RUNNING = "running"
DEDUPE_STATUS_COMPLETE = "complete"
DEDUPE_STATUS_FAILED = "failed"
DEFAULT_DEDUPE_CHUNK_SIZE = 25
DEFAULT_DEDUPE_MAX_GROUPS = 25
DEFAULT_CONTINUE_RUNTIME_SECONDS = 15
MAX_DEDUPE_CHUNK_SIZE = 100
MAX_DEDUPE_GROUPS = 200
LOW_CONFIDENCE_THRESHOLD = 0.90
SUPPORTED_DEDUPE_NAMESPACES = {
    FileNamespace.GOOGLE1.value,
    FileNamespace.GOOGLE2.value,
    FileNamespace.ICLOUD.value,
    FileNamespace.DOCUMENT_VAULT.value,
}
SUPPORTED_DEDUPE_STRATEGIES = {"exact_hash", "normalized_name_size", "content_hash", "all"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _coerce_chunk_size(value: int | None, *, default: int) -> int:
    if value is None:
        return default
    return min(max(int(value), 1), MAX_DEDUPE_CHUNK_SIZE)


def _coerce_max_groups(value: int | None) -> int | None:
    if value is None:
        return DEFAULT_DEDUPE_MAX_GROUPS
    return min(max(int(value), 1), MAX_DEDUPE_GROUPS)


def _normalize_path_scope(path_scope: str | None) -> str | None:
    cleaned = str(path_scope or "").replace("\\", "/").strip()
    return cleaned.strip("/") or None


def _normalize_namespaces(namespaces: list[str] | None) -> list[str]:
    raw = namespaces or [
        FileNamespace.GOOGLE1.value,
        FileNamespace.GOOGLE2.value,
        FileNamespace.ICLOUD.value,
    ]
    cleaned: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value in SUPPORTED_DEDUPE_NAMESPACES and value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        raise FileMutationPolicyError("At least one supported namespace is required.")
    return cleaned


def _normalize_strategy(strategy: str | None) -> str:
    cleaned = str(strategy or "exact_hash").strip().lower()
    if cleaned not in SUPPORTED_DEDUPE_STRATEGIES:
        raise FileMutationPolicyError("Unsupported dedupe strategy.")
    return cleaned


def _is_internal_index_path(path_value: str) -> bool:
    cleaned = str(path_value or "").strip().lstrip("/")
    if not cleaned:
        return False
    return any(part.startswith("_") for part in cleaned.split("/"))


def _record_namespace(path_value: str) -> str | None:
    cleaned = str(path_value or "").strip().lstrip("/")
    if not cleaned:
        return None
    return cleaned.split("/", 1)[0]


def _relative_record_path(path_value: str) -> str:
    cleaned = str(path_value or "").strip().lstrip("/")
    if not cleaned or "/" not in cleaned:
        return ""
    return cleaned.split("/", 1)[1]


def _normalized_name(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(name or ""))
    return " ".join(part for part in cleaned.split() if part)


def _is_backupish_path(path_value: str) -> bool:
    lowered = str(path_value or "").lower()
    return any(marker in lowered for marker in ("/_changes_backup/", "/trash/", "/tmp/", "/temp/"))


def _resolve_source_path_for_record(record: FileRecord) -> Path | None:
    namespace_value = _record_namespace(record.path)
    if namespace_value not in SUPPORTED_DEDUPE_NAMESPACES:
        return None
    try:
        return resolve_live_path(
            namespace=FileNamespace(namespace_value),
            relative_path=_relative_record_path(record.path),
            allow_internal=False,
        )
    except Exception:
        return None


def _source_exists_for_record(record: FileRecord) -> bool:
    source_path = _resolve_source_path_for_record(record)
    return bool(source_path and source_path.exists() and source_path.is_file())


def _candidate_filters(*, namespaces: list[str], path_scope: str | None) -> list[object]:
    predicates = [
        FileRecord.is_deleted.is_(False),
        or_(*[FileRecord.path.like(f"/{namespace}/%") for namespace in namespaces]),
    ]
    if path_scope:
        normalized = path_scope.lower()
        predicates.append(func.lower(FileRecord.path).like(f"%{normalized}%"))
    return predicates


def _count_candidates(session: Session, *, namespaces: list[str], path_scope: str | None) -> int:
    statement = select(func.count()).select_from(FileRecord).where(
        *_candidate_filters(namespaces=namespaces, path_scope=path_scope)
    )
    return int(session.scalar(statement) or 0)


def _load_job_state(job: DedupeJob) -> dict[str, object]:
    if not job.state_json:
        return {"cursor_file_id": 0}
    try:
        payload = json.loads(job.state_json)
    except json.JSONDecodeError:
        return {"cursor_file_id": 0}
    if not isinstance(payload, dict):
        return {"cursor_file_id": 0}
    return payload


def _store_job_state(job: DedupeJob, state: dict[str, object]) -> None:
    job.state_json = json.dumps(state, ensure_ascii=False)


def _strategy_list(strategy: str) -> list[str]:
    if strategy == "all":
        return ["exact_hash", "normalized_name_size", "content_hash"]
    return [strategy]


def _iter_candidate_rows(
    session: Session,
    *,
    namespaces: list[str],
    path_scope: str | None,
    after_file_id: int,
    limit: int,
    include_extracted_hash: bool,
) -> list[tuple[FileRecord, str | None]]:
    if include_extracted_hash:
        statement = (
            select(FileRecord, ExtractedContent.content_hash)
            .outerjoin(ExtractedContent, ExtractedContent.file_id == FileRecord.id)
            .where(
                *_candidate_filters(namespaces=namespaces, path_scope=path_scope),
                FileRecord.id > after_file_id,
            )
            .order_by(FileRecord.id.asc())
            .limit(limit)
        )
        rows = session.execute(statement).all()
        return [(record, extracted_hash) for record, extracted_hash in rows]

    statement = (
        select(FileRecord)
        .where(
            *_candidate_filters(namespaces=namespaces, path_scope=path_scope),
            FileRecord.id > after_file_id,
        )
        .order_by(FileRecord.id.asc())
        .limit(limit)
    )
    return [(record, None) for record in session.scalars(statement).all()]


def _compute_live_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprints_for_record(
    *,
    record: FileRecord,
    extracted_content_hash: str | None,
    strategies: list[str],
) -> list[tuple[str, str, str, dict[str, object], bool]]:
    results: list[tuple[str, str, str, dict[str, object], bool]] = []
    source_path = _resolve_source_path_for_record(record)
    source_exists = bool(source_path and source_path.exists() and source_path.is_file())
    live_hash: str | None = None

    for strategy in strategies:
        if strategy == "normalized_name_size":
            normalized = _normalized_name(record.name)
            if not normalized:
                continue
            raw = f"{normalized}:{record.size_bytes or 0}"
            results.append(
                (
                    strategy,
                    sha256(f"{strategy}|{raw}".encode("utf-8")).hexdigest(),
                    raw,
                    {
                        "normalized_name": normalized,
                        "size_bytes": record.size_bytes,
                    },
                    source_exists,
                )
            )
            continue

        if strategy == "content_hash":
            if not extracted_content_hash:
                continue
            raw = f"{extracted_content_hash}:{record.size_bytes or 0}"
            results.append(
                (
                    strategy,
                    sha256(f"{strategy}|{raw}".encode("utf-8")).hexdigest(),
                    extracted_content_hash,
                    {
                        "content_hash": extracted_content_hash,
                        "size_bytes": record.size_bytes,
                    },
                    source_exists,
                )
            )
            continue

        if strategy == "exact_hash":
            if not source_exists or source_path is None:
                continue
            if live_hash is None:
                live_hash = _compute_live_hash(source_path)
            raw = f"{live_hash}:{record.size_bytes or 0}"
            results.append(
                (
                    strategy,
                    sha256(f"{strategy}|{raw}".encode("utf-8")).hexdigest(),
                    live_hash,
                    {
                        "content_hash": live_hash,
                        "size_bytes": record.size_bytes,
                    },
                    True,
                )
            )

    return results


def _group_unique_id(*, job_id: str, strategy: str, fingerprint: str) -> str:
    return sha256(f"{job_id}|{strategy}|{fingerprint}".encode("utf-8")).hexdigest()[:24]


def _pick_recommended_keep(items: list[tuple[DedupeGroupItem, FileRecord | None]]) -> int | None:
    ranked: list[tuple[tuple[int, int, int, int, str, int], int]] = []
    for index, (item, record) in enumerate(items):
        if record is None or item.file_record_id is None:
            continue
        source_exists_rank = 1 if item.source_exists else 0
        modified_rank = int(record.modified_at.timestamp()) if record.modified_at else 0
        clean_path_rank = 1 if not _is_backupish_path(record.path) else 0
        ranked.append(
            (
                (
                    -source_exists_rank,
                    -modified_rank,
                    -clean_path_rank,
                    len(str(record.path or "")),
                    str(record.path or "").lower(),
                    record.id or 0,
                ),
                index,
            )
        )
    if not ranked:
        return None
    ranked.sort()
    chosen_index = ranked[0][1]
    return items[chosen_index][0].file_record_id


def _group_confidence_and_reason(strategy: str, member_count: int) -> tuple[float, str]:
    if strategy == "exact_hash":
        return 0.99, f"Exact byte hash and size match across {member_count} files."
    if strategy == "content_hash":
        return 0.93, f"Extracted content hash and size match across {member_count} files."
    return 0.55, f"Normalized filename and size match across {member_count} files; review before moving."


def _refresh_group_summary(session: Session, *, group: DedupeGroup) -> None:
    items = session.execute(
        select(DedupeGroupItem, FileRecord)
        .outerjoin(FileRecord, FileRecord.id == DedupeGroupItem.file_record_id)
        .where(DedupeGroupItem.dedupe_group_id == group.id)
        .order_by(DedupeGroupItem.id.asc())
    ).all()
    member_count = len(items)
    group.duplicate_count = max(member_count - 1, 0)
    if not items:
        return

    recommended_keep_id = _pick_recommended_keep(items)
    confidence, reason = _group_confidence_and_reason(group.strategy or "normalized_name_size", member_count)
    total_size = sum(int(item.size_bytes or 0) for item, _record in items)
    members = [record.path for _item, record in items if record is not None]
    canonical_record = next(
        (record for item, record in items if item.file_record_id == recommended_keep_id and record is not None),
        None,
    )
    group.canonical_file_record_id = recommended_keep_id
    group.recommended_keep_file_record_id = recommended_keep_id
    group.canonical_item_path = canonical_record.path if canonical_record is not None else group.canonical_item_path
    group.total_size_bytes = total_size
    group.confidence = confidence
    group.reason = reason
    evidence = json.loads(group.evidence_json) if group.evidence_json else {}
    evidence["members"] = members
    evidence["member_count"] = member_count
    evidence["total_size"] = total_size
    group.evidence_json = json.dumps(evidence, ensure_ascii=False)
    for item, _record in items:
        item.decision_role = "canonical" if item.file_record_id == recommended_keep_id else "duplicate"


def _upsert_group_membership(
    session: Session,
    *,
    job: DedupeJob,
    strategy: str,
    fingerprint: str,
    detail_value: str,
    evidence: dict[str, object],
    record: FileRecord,
    source_exists: bool,
) -> None:
    dedupe_group_id = _group_unique_id(job_id=job.job_id, strategy=strategy, fingerprint=fingerprint)
    group = session.scalar(select(DedupeGroup).where(DedupeGroup.dedupe_group_id == dedupe_group_id))
    if group is None:
        group = DedupeGroup(
            dedupe_group_id=dedupe_group_id,
            dedupe_job_id=job.id,
            group_fingerprint=fingerprint,
            strategy=strategy,
            status="candidate",
            canonical_item_path=record.path,
            total_size_bytes=record.size_bytes,
            duplicate_count=0,
            canonical_file_record_id=record.id,
            recommended_keep_file_record_id=record.id,
            confidence=0.0,
            reason="Awaiting at least one duplicate match.",
            evidence_json=json.dumps(evidence, ensure_ascii=False),
            decision_notes="Generated by dedupe job analysis dry-run.",
        )
        session.add(group)
        session.flush()

    item = session.scalar(
        select(DedupeGroupItem).where(
            DedupeGroupItem.dedupe_group_id == group.id,
            DedupeGroupItem.file_record_id == record.id,
        )
    )
    if item is None:
        item = DedupeGroupItem(
            dedupe_group_id=group.id,
            file_record_id=record.id,
            path_at_analysis_time=record.path,
            content_hash=detail_value,
            size_bytes=record.size_bytes,
            similarity_score=1.0 if strategy != "normalized_name_size" else 0.55,
            decision_role="duplicate",
            source_exists=source_exists,
        )
        session.add(item)
        session.flush()

    _refresh_group_summary(session, group=group)


def _job_payload(job: DedupeJob) -> dict[str, object]:
    namespaces = json.loads(job.namespaces_json)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "namespaces": namespaces,
        "strategy": job.strategy,
        "processed_count": job.processed_count,
        "remaining_count": job.remaining_count,
        "groups_found": job.groups_found,
        "started_at": _iso(job.started_at),
        "updated_at": _iso(job.updated_at),
        "completed_at": _iso(job.completed_at),
        "error": job.error_message,
    }


def _refresh_job_counts(session: Session, *, job: DedupeJob) -> None:
    job.groups_found = int(
        session.scalar(
            select(func.count())
            .select_from(DedupeGroup)
            .where(
                DedupeGroup.dedupe_job_id == job.id,
                DedupeGroup.duplicate_count >= 1,
            )
        )
        or 0
    )
    job.remaining_count = max(job.total_candidates - job.processed_count, 0)
    job.updated_at = _utc_now()


def _load_job_by_public_id(session: Session, *, job_id: str) -> DedupeJob:
    job = session.scalar(select(DedupeJob).where(DedupeJob.job_id == job_id))
    if job is None:
        raise FileMutationPolicyError("Dedupe job was not found.")
    return job


def start_dedupe_job(
    session: Session,
    *,
    namespaces: list[str] | None,
    path_scope: str | None = None,
    strategy: str = "exact_hash",
    chunk_size: int | None = None,
    max_groups: int | None = None,
    dry_run: bool = True,
) -> dict[str, object]:
    normalized_namespaces = _normalize_namespaces(namespaces)
    normalized_strategy = _normalize_strategy(strategy)
    normalized_scope = _normalize_path_scope(path_scope)
    active_chunk_size = _coerce_chunk_size(chunk_size, default=DEFAULT_DEDUPE_CHUNK_SIZE)
    active_max_groups = _coerce_max_groups(max_groups)
    job_id = uuid4().hex
    total_candidates = _count_candidates(
        session,
        namespaces=normalized_namespaces,
        path_scope=normalized_scope,
    )
    job = DedupeJob(
        job_id=job_id,
        status=DEDUPE_STATUS_QUEUED,
        strategy=normalized_strategy,
        namespaces_json=json.dumps(normalized_namespaces),
        path_scope=normalized_scope,
        dry_run=dry_run,
        chunk_size=active_chunk_size,
        max_groups=active_max_groups,
        total_candidates=total_candidates,
        processed_count=0,
        remaining_count=total_candidates,
        groups_found=0,
    )
    _store_job_state(job, {"cursor_file_id": 0})
    session.add(job)
    session.commit()
    return {
        "job_id": job.job_id,
        "status": job.status,
        "queued_count": job.remaining_count,
        "message": "Dedupe job created. Call continue_icloud_dedupe_job to process bounded chunks.",
    }


def continue_dedupe_job(
    session: Session,
    *,
    job_id: str,
    max_runtime_seconds: int | None = None,
    chunk_size: int | None = None,
) -> dict[str, object]:
    job = _load_job_by_public_id(session, job_id=job_id)
    if job.status == DEDUPE_STATUS_COMPLETE:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "processed_count": job.processed_count,
            "remaining_count": job.remaining_count,
            "groups_found": job.groups_found,
            "message": "Dedupe job is already complete.",
        }

    if job.status == DEDUPE_STATUS_FAILED:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "processed_count": job.processed_count,
            "remaining_count": job.remaining_count,
            "groups_found": job.groups_found,
            "message": job.error_message or "Dedupe job previously failed.",
        }

    state = _load_job_state(job)
    cursor_file_id = int(state.get("cursor_file_id") or 0)
    active_chunk_size = _coerce_chunk_size(chunk_size, default=job.chunk_size)
    runtime_budget = max(int(max_runtime_seconds or DEFAULT_CONTINUE_RUNTIME_SECONDS), 1)
    started = time.monotonic()
    namespaces = json.loads(job.namespaces_json)
    include_extracted_hash = "content_hash" in _strategy_list(job.strategy)
    rows = _iter_candidate_rows(
        session,
        namespaces=namespaces,
        path_scope=job.path_scope,
        after_file_id=cursor_file_id,
        limit=active_chunk_size,
        include_extracted_hash=include_extracted_hash,
    )
    job.status = DEDUPE_STATUS_RUNNING
    strategies = _strategy_list(job.strategy)

    try:
        for record, extracted_hash in rows:
            if _is_internal_index_path(record.path):
                job.processed_count += 1
                cursor_file_id = record.id
                continue

            for (
                strategy_name,
                fingerprint,
                detail_value,
                evidence,
                source_exists,
            ) in _fingerprints_for_record(
                record=record,
                extracted_content_hash=extracted_hash,
                strategies=strategies,
            ):
                _upsert_group_membership(
                    session,
                    job=job,
                    strategy=strategy_name,
                    fingerprint=fingerprint,
                    detail_value=detail_value,
                    evidence=evidence,
                    record=record,
                    source_exists=source_exists,
                )
            job.processed_count += 1
            cursor_file_id = record.id
            _refresh_job_counts(session, job=job)
            _store_job_state(job, {"cursor_file_id": cursor_file_id})
            session.commit()
            if job.max_groups is not None and job.groups_found >= job.max_groups:
                job.status = DEDUPE_STATUS_COMPLETE
                job.completed_at = _utc_now()
                _refresh_job_counts(session, job=job)
                _store_job_state(job, {"cursor_file_id": cursor_file_id})
                session.commit()
                return {
                    "job_id": job.job_id,
                    "status": job.status,
                    "processed_count": job.processed_count,
                    "remaining_count": job.remaining_count,
                    "groups_found": job.groups_found,
                    "message": "Dedupe job reached the requested max_groups limit.",
                }
            if time.monotonic() - started >= runtime_budget:
                break
    except Exception as exc:
        job.status = DEDUPE_STATUS_FAILED
        job.error_message = str(exc)
        job.updated_at = _utc_now()
        session.commit()
        return {
            "job_id": job.job_id,
            "status": job.status,
            "processed_count": job.processed_count,
            "remaining_count": job.remaining_count,
            "groups_found": job.groups_found,
            "message": str(exc),
        }

    _refresh_job_counts(session, job=job)
    _store_job_state(job, {"cursor_file_id": cursor_file_id})
    if not rows or job.remaining_count <= 0:
        job.status = DEDUPE_STATUS_COMPLETE
        job.completed_at = _utc_now()
    else:
        job.status = DEDUPE_STATUS_RUNNING
    session.commit()
    return {
        "job_id": job.job_id,
        "status": job.status,
        "processed_count": job.processed_count,
        "remaining_count": job.remaining_count,
        "groups_found": job.groups_found,
        "message": "Processed a bounded dedupe chunk.",
    }


def get_dedupe_job_status(session: Session, *, job_id: str) -> dict[str, object]:
    job = _load_job_by_public_id(session, job_id=job_id)
    return _job_payload(job)


def list_dedupe_groups(
    session: Session,
    *,
    job_id: str | None = None,
    limit: int = 25,
    offset: int = 0,
    strategy: str | None = None,
    min_group_size: int = 2,
) -> dict[str, object]:
    statement = select(DedupeGroup).where(DedupeGroup.duplicate_count >= max(min_group_size - 1, 1))
    if job_id:
        job = _load_job_by_public_id(session, job_id=job_id)
        statement = statement.where(DedupeGroup.dedupe_job_id == job.id)
    if strategy and strategy != "all":
        statement = statement.where(DedupeGroup.strategy == strategy)
    statement = statement.order_by(DedupeGroup.updated_at.desc(), DedupeGroup.id.asc()).offset(offset).limit(limit)
    groups = session.scalars(statement).all()
    payload = [
        {
            "dedupe_group_id": group.dedupe_group_id,
            "strategy": group.strategy,
            "member_count": group.duplicate_count + 1,
            "total_size": group.total_size_bytes or 0,
            "recommended_keep_file_id": group.recommended_keep_file_record_id,
            "confidence": group.confidence,
            "reason": group.reason,
        }
        for group in groups
    ]
    return {"groups": payload, "count": len(payload)}


def _file_payload_for_group_member(
    *,
    item: DedupeGroupItem,
    record: FileRecord | None,
    recommended_keep_id: int | None,
    group_strategy: str | None,
) -> dict[str, object]:
    namespace = _record_namespace(record.path) if record is not None else None
    source_path = _resolve_source_path_for_record(record) if record is not None else None
    source_exists = bool(source_path and source_path.exists() and source_path.is_file())
    recommended_action = "review"
    if item.file_record_id == recommended_keep_id:
        recommended_action = "keep"
    elif (group_strategy in {"exact_hash", "content_hash"}) and source_exists:
        recommended_action = "move_to_backup"
    return {
        "file_id": item.file_record_id,
        "namespace": namespace,
        "relative_path": _relative_record_path(record.path) if record is not None else item.path_at_analysis_time,
        "canonical_source_path": str(source_path) if source_path is not None else None,
        "size": item.size_bytes,
        "mtime": _iso(record.modified_at) if record is not None else None,
        "content_hash": item.content_hash,
        "source_exists": source_exists,
        "is_recommended_keep": item.file_record_id == recommended_keep_id,
        "recommended_action": recommended_action,
    }


def get_dedupe_group(session: Session, *, dedupe_group_id: str) -> dict[str, object] | None:
    group = session.scalar(select(DedupeGroup).where(DedupeGroup.dedupe_group_id == dedupe_group_id))
    if group is None:
        return None
    rows = session.execute(
        select(DedupeGroupItem, FileRecord)
        .outerjoin(FileRecord, FileRecord.id == DedupeGroupItem.file_record_id)
        .where(DedupeGroupItem.dedupe_group_id == group.id)
        .order_by(DedupeGroupItem.id.asc())
    ).all()
    return {
        "dedupe_group_id": group.dedupe_group_id,
        "strategy": group.strategy,
        "confidence": group.confidence,
        "reason": group.reason,
        "recommended_keep_file_id": group.recommended_keep_file_record_id,
        "members": [
            _file_payload_for_group_member(
                item=item,
                record=record,
                recommended_keep_id=group.recommended_keep_file_record_id,
                group_strategy=group.strategy,
            )
            for item, record in rows
        ],
    }


def _change_set_payload_for_multi_move(
    *,
    change_set_id: str,
    items: list[dict[str, object]],
    actor: str,
) -> dict[str, object]:
    primary_namespace = str(items[0]["namespace"])
    return {
        "change_set_id": change_set_id,
        "namespace": primary_namespace,
        "actor": actor,
        "operation": "dedupe-move-to-backup",
        "status": "moved" if items else "dry_run",
        "items": items,
    }


def apply_dedupe_group(
    session: Session,
    *,
    dedupe_group_id: str,
    keep_file_id: int,
    move_to_backup_file_ids: list[int],
    dry_run: bool = True,
    actor: str = "plugin-api",
) -> dict[str, object]:
    group = session.scalar(select(DedupeGroup).where(DedupeGroup.dedupe_group_id == dedupe_group_id))
    if group is None:
        raise FileMutationPolicyError("Dedupe group not found.")
    if keep_file_id in move_to_backup_file_ids:
        raise FileMutationPolicyError("keep_file_id cannot also be moved to backup.")
    if (group.confidence or 0.0) < LOW_CONFIDENCE_THRESHOLD:
        raise FileMutationPolicyError("Low-confidence dedupe groups require review and cannot be applied.")

    rows = session.execute(
        select(DedupeGroupItem, FileRecord)
        .outerjoin(FileRecord, FileRecord.id == DedupeGroupItem.file_record_id)
        .where(DedupeGroupItem.dedupe_group_id == group.id)
    ).all()
    members_by_id = {
        item.file_record_id: (item, record)
        for item, record in rows
        if item.file_record_id is not None and record is not None
    }
    if keep_file_id not in members_by_id:
        raise FileMutationPolicyError("keep_file_id is not a member of the dedupe group.")
    unknown_ids = [file_id for file_id in move_to_backup_file_ids if file_id not in members_by_id]
    if unknown_ids:
        raise FileMutationPolicyError("One or more move_to_backup_file_ids are not members of the dedupe group.")

    recommended_keep = group.recommended_keep_file_record_id
    if recommended_keep is not None and keep_file_id != recommended_keep:
        raise FileMutationPolicyError("Only the recommended keep file can be used for this confidence level.")

    change_set_id = uuid4().hex
    planned_items: list[dict[str, object]] = []
    for file_id in move_to_backup_file_ids:
        item, record = members_by_id[file_id]
        namespace_value = _record_namespace(record.path)
        if namespace_value is None:
            raise FileMutationPolicyError("Member path is missing a namespace prefix.")
        namespace = FileNamespace(namespace_value)
        relative_path = _relative_record_path(record.path)
        live_path = resolve_live_path(
            namespace=namespace,
            relative_path=relative_path,
            allow_internal=False,
        )
        if not live_path.exists() or not live_path.is_file():
            raise FileMutationPolicyError("A file selected for backup no longer exists.")
        backup_dir = _changes_backup_root(namespace) / change_set_id / "payload"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / live_path.name
        planned_items.append(
            {
                "namespace": namespace.value,
                "original_relative_path": relative_path,
                "backup_path": str(backup_path),
                "file_record_id": file_id,
                "canonical_source_path": str(live_path),
                "document_note_paths": [],
            }
        )

    if dry_run:
        return {
            "status": "dry_run",
            "change_set_id": change_set_id,
            "kept_file_id": keep_file_id,
            "moved_to_backup": [],
            "dry_run": True,
            "message": "Dry run only. No files were moved.",
        }

    payload = _change_set_payload_for_multi_move(
        change_set_id=change_set_id,
        items=planned_items,
        actor=actor,
    )
    _write_change_set_metadata(FileNamespace(planned_items[0]["namespace"]), change_set_id, payload)

    for entry in planned_items:
        namespace = FileNamespace(str(entry["namespace"]))
        relative_path = str(entry["original_relative_path"])
        live_path = resolve_live_path(namespace=namespace, relative_path=relative_path, allow_internal=False)
        backup_path = Path(str(entry["backup_path"]))
        move(str(live_path), str(backup_path))
        vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
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
                canonical_source_path=str(live_path),
            )
        ]
        entry["document_note_paths"] = [str(path) for path in _iter_note_paths_for_canonical_source(
            vault_root=vault_root,
            canonical_source_path=str(live_path),
        )]
        item_payload = {
            "change_set_id": change_set_id,
            "namespace": namespace.value,
            "actor": actor,
            "operation": "dedupe-move-to-backup",
            "status": "moved",
            "original_relative_path": relative_path,
            "backup_path": str(backup_path),
        }
        for note_id in note_ids:
            if note_id is not None:
                _persist_change_set(
                    session,
                    payload=item_payload,
                    item_type="document_vault_note",
                    document_note_record_id=note_id,
                )
        _persist_change_set(
            session,
            payload=item_payload,
            item_type="source_file",
            file_record_id=_find_file_record_id(
                session,
                namespace=namespace,
                relative_path=relative_path,
            ),
            content_hash_before=sha256(backup_path.read_bytes()).hexdigest(),
        )

    session.commit()
    return {
        "status": "moved",
        "change_set_id": change_set_id,
        "kept_file_id": keep_file_id,
        "moved_to_backup": [entry["file_record_id"] for entry in planned_items],
        "dry_run": False,
        "message": "Moved duplicate files into namespace-specific _CHANGES_BACKUP storage.",
    }


def analyze_duplicate_groups(
    session: Session,
    *,
    namespaces: list[str],
    limit: int = 25,
) -> dict[str, object]:
    payload = start_dedupe_job(
        session,
        namespaces=namespaces,
        strategy="exact_hash",
        chunk_size=min(limit, DEFAULT_DEDUPE_CHUNK_SIZE),
        max_groups=limit,
        dry_run=True,
    )
    payload["message"] = (
        "Synchronous duplicate analysis is deprecated. "
        "A resumable dedupe job was created instead; continue it in bounded chunks."
    )
    payload["deprecated"] = True
    return payload
