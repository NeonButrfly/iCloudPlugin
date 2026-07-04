from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from icloud_index_service.models.cloud_vault_task import CloudVaultTask
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.dedupe_workflow_service import (
    apply_dedupe_group,
    continue_dedupe_job,
    list_dedupe_groups,
    start_dedupe_job,
)
from icloud_index_service.services.file_mutation_service import (
    FileMutationPolicyError,
    classify_file_and_create_document_vault_note_fallback,
    create_document_vault_note,
    restore_change_set,
)
from icloud_index_service.services.search_service import search_files

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELED = "canceled"

TASK_TYPE_CHATGPT_FIRST_FILE_NOTE = "create_document_vault_note_from_file_id_chatgpt_first"
TASK_TYPE_SEARCH_NOTES = "create_document_vault_notes_from_search"
TASK_TYPE_FALLBACK_FILE_NOTE = "classifier_fallback_note_from_file_id"
TASK_TYPE_DEDUPE_ANALYSIS = "dedupe_analysis"
TASK_TYPE_APPLY_DEDUPE_GROUP = "apply_dedupe_group"
TASK_TYPE_RESTORE_CHANGE_SET = "restore_change_set"

SUPPORTED_TASK_TYPES = {
    TASK_TYPE_CHATGPT_FIRST_FILE_NOTE,
    TASK_TYPE_SEARCH_NOTES,
    TASK_TYPE_FALLBACK_FILE_NOTE,
    TASK_TYPE_DEDUPE_ANALYSIS,
    TASK_TYPE_APPLY_DEDUPE_GROUP,
    TASK_TYPE_RESTORE_CHANGE_SET,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads_object(raw_value: str | None, *, default: dict[str, object] | None = None) -> dict[str, object]:
    if not raw_value:
        return default or {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return default or {}
    return parsed if isinstance(parsed, dict) else (default or {})


def _serialize_task(task: CloudVaultTask) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status,
        "priority": task.priority,
        "idempotency_key": task.idempotency_key,
        "change_set_id": task.change_set_id,
        "input": _loads_object(task.input_json),
        "progress": _loads_object(task.progress_json),
        "result": _loads_object(task.result_json),
        "error": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "heartbeat_at": task.heartbeat_at.isoformat() if task.heartbeat_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "canceled_at": task.canceled_at.isoformat() if task.canceled_at else None,
    }


def _load_task_by_public_id(session: Session, *, task_id: str) -> CloudVaultTask:
    task = session.scalar(select(CloudVaultTask).where(CloudVaultTask.task_id == task_id))
    if task is None:
        raise FileMutationPolicyError("Cloud-vault task was not found.")
    return task


def _existing_task_for_idempotency(
    session: Session,
    *,
    idempotency_key: str | None,
) -> CloudVaultTask | None:
    if not idempotency_key:
        return None
    return session.scalar(
        select(CloudVaultTask).where(CloudVaultTask.idempotency_key == idempotency_key)
    )


def _derive_note_folder(*, primary_label: str | None) -> str:
    cleaned = str(primary_label or "").strip().lower()
    if not cleaned or cleaned in {"unknown", "needs-review"}:
        return "02 Needs Review/queued"
    return f"01 Classified/{cleaned}"


def _derive_note_title(*, file_record: FileRecord) -> str:
    return file_record.name.rsplit(".", 1)[0] or file_record.name or f"file-{file_record.id}"


def _derive_note_summary(*, file_record: FileRecord) -> str:
    return f"Queued note for {file_record.name}."


def queue_cloud_vault_task(
    session: Session,
    *,
    task_type: str,
    input_payload: dict[str, object],
    idempotency_key: str | None = None,
    priority: int = 100,
) -> dict[str, object]:
    if task_type not in SUPPORTED_TASK_TYPES:
        raise FileMutationPolicyError("Unsupported cloud-vault task type.")
    existing = _existing_task_for_idempotency(session, idempotency_key=idempotency_key)
    if existing is not None:
        return {
            **_serialize_task(existing),
            "message": "Reused existing task for the provided idempotency key.",
        }
    task = CloudVaultTask(
        task_id=uuid4().hex,
        task_type=task_type,
        status=TASK_STATUS_QUEUED,
        input_json=_dumps(input_payload),
        progress_json=_dumps({}),
        idempotency_key=idempotency_key,
        priority=int(priority),
    )
    session.add(task)
    session.commit()
    return {
        "task_id": task.task_id,
        "status": task.status,
        "message": "Cloud-vault task queued.",
    }


def _mark_task_failed(session: Session, *, task: CloudVaultTask, message: str) -> dict[str, object]:
    task.status = TASK_STATUS_FAILED
    task.error_message = str(message)
    task.updated_at = _utc_now()
    task.completed_at = _utc_now()
    session.commit()
    payload = _serialize_task(task)
    payload["message"] = str(message)
    return payload


def _mark_task_completed(
    session: Session,
    *,
    task: CloudVaultTask,
    result_payload: dict[str, object],
) -> dict[str, object]:
    task.status = TASK_STATUS_COMPLETED
    task.result_json = _dumps(result_payload)
    task.error_message = None
    task.updated_at = _utc_now()
    task.completed_at = _utc_now()
    if isinstance(result_payload.get("change_set_id"), str):
        task.change_set_id = str(result_payload["change_set_id"])
    session.commit()
    payload = _serialize_task(task)
    payload["message"] = "Cloud-vault task completed."
    return payload


def _run_chatgpt_first_file_note(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    file_id = int(payload.get("file_id") or 0)
    if file_id <= 0:
        raise FileMutationPolicyError("file_id is required.")
    fallback_enabled = bool(payload.get("fallback_enabled"))
    fallback_reason = str(payload.get("fallback_reason") or "manual_fallback")
    attach_originals = bool(payload.get("attach_originals", True))
    file_record = session.get(FileRecord, file_id)
    if file_record is None:
        raise FileMutationPolicyError("Indexed file record was not found.")
    relative_folder = str(payload.get("chatgpt_relative_folder") or "").strip()
    visible_title = str(payload.get("chatgpt_visible_title") or "").strip()
    summary = str(payload.get("chatgpt_summary") or "").strip()
    if not relative_folder:
        relative_folder = _derive_note_folder(primary_label=None)
    if not visible_title:
        visible_title = _derive_note_title(file_record=file_record)
    if not summary:
        summary = _derive_note_summary(file_record=file_record)
    try:
        return create_document_vault_note(
            relative_folder=relative_folder,
            visible_title=visible_title,
            summary=summary,
            file_id=file_id,
            attach_originals=attach_originals,
            actor="queued-task",
            session=session,
        )
    except FileMutationPolicyError:
        if not fallback_enabled:
            raise
        return classify_file_and_create_document_vault_note_fallback(
            file_id=file_id,
            fallback_reason=fallback_reason,
            force_reclassify=bool(payload.get("force_reclassify", False)),
            summary_mode=str(payload.get("fallback_summary_mode") or "classifier"),
            title_mode=str(payload.get("fallback_title_mode") or "classifier"),
            attach_originals=attach_originals,
            idempotency_key=task.idempotency_key,
            actor="queued-task",
            session=session,
        )


def _run_search_notes(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    progress = _loads_object(task.progress_json)
    if not progress:
        matches = search_files(
            session,
            query=str(payload.get("query") or ""),
            limit=min(max(int(payload.get("limit") or 10), 1), 50),
            path_scope=str(payload.get("path_scope") or "") or None,
        )
        namespace = str(payload.get("namespace") or "").strip().strip("/")
        if namespace:
            matches = [
                match for match in matches
                if str(match.get("path") or "").startswith(f"/{namespace}/")
            ]
        progress = {
            "matched_file_ids": [
                int(match["file_id"])
                for match in matches
                if isinstance(match.get("file_id"), int)
            ],
            "cursor": 0,
            "results": [],
        }
    file_ids = [int(item) for item in progress.get("matched_file_ids", []) if int(item) > 0]
    if not file_ids:
        task.progress_json = _dumps(
            {
                **progress,
                "matched_count": 0,
                "processed_count": 0,
            }
        )
        return {
            "matched_count": 0,
            "processed_count": 0,
            "results": [],
        }
    cursor = int(progress.get("cursor") or 0)
    batch_size = min(max(int(payload.get("batch_size") or 10), 1), 25)
    note_mode = str(payload.get("note_mode") or "minimal").strip()
    results = list(progress.get("results") or [])
    for file_id in file_ids[cursor : cursor + batch_size]:
        file_record = session.get(FileRecord, file_id)
        if file_record is None:
            results.append({"file_id": file_id, "status": "failed", "message": "File not found."})
            continue
        if note_mode == "classifier_fallback":
            result = classify_file_and_create_document_vault_note_fallback(
                file_id=file_id,
                fallback_reason="manual_fallback",
                force_reclassify=False,
                summary_mode="classifier",
                title_mode="classifier",
                attach_originals=True,
                actor="queued-task",
                session=session,
            )
        else:
            result = create_document_vault_note(
                relative_folder=_derive_note_folder(primary_label=str(file_record.name).split(".")[0]),
                visible_title=_derive_note_title(file_record=file_record),
                summary=_derive_note_summary(file_record=file_record),
                file_id=file_id,
                attach_originals=True,
                actor="queued-task",
                session=session,
            )
        results.append(result)
    cursor = min(cursor + batch_size, len(file_ids))
    task.progress_json = _dumps(
        {
            **progress,
            "matched_file_ids": file_ids,
            "cursor": cursor,
            "results": results,
            "matched_count": len(file_ids),
            "processed_count": len(results),
        }
    )
    if cursor < len(file_ids):
        task.result_json = _dumps(
            {
                "matched_count": len(file_ids),
                "processed_count": len(results),
                "results": results,
                "continued": True,
            }
        )
        task.updated_at = _utc_now()
        session.commit()
        payload_result = _serialize_task(task)
        payload_result["message"] = "Processed a bounded search-note task chunk."
        return payload_result
    return {
        "matched_count": len(file_ids),
        "processed_count": len(results),
        "results": results,
    }


def _run_fallback_file_note(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    return classify_file_and_create_document_vault_note_fallback(
        file_id=int(payload.get("file_id") or 0),
        fallback_reason=str(payload.get("fallback_reason") or "manual_fallback"),
        force_reclassify=bool(payload.get("force_reclassify", False)),
        summary_mode=str(payload.get("summary_mode") or "classifier"),
        title_mode=str(payload.get("title_mode") or "classifier"),
        attach_originals=bool(payload.get("attach_originals", True)),
        idempotency_key=task.idempotency_key,
        actor="queued-task",
        session=session,
    )


def _run_dedupe_analysis(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    progress = _loads_object(task.progress_json)
    dedupe_job_id = str(progress.get("dedupe_job_id") or "")
    if not dedupe_job_id:
        created = start_dedupe_job(
            session,
            namespaces=[str(item) for item in payload.get("namespaces", [])] or None,
            path_scope=str(payload.get("path_scope") or "") or None,
            strategy=str(payload.get("strategy") or "exact_hash"),
            chunk_size=int(payload.get("chunk_size") or 25),
            max_groups=int(payload.get("max_groups") or 25),
            dry_run=bool(payload.get("dry_run", True)),
        )
        dedupe_job_id = str(created["job_id"])
        progress = {"dedupe_job_id": dedupe_job_id}
    continued = continue_dedupe_job(
        session,
        job_id=dedupe_job_id,
        max_runtime_seconds=int(payload.get("max_runtime_seconds") or 15),
        chunk_size=int(payload.get("chunk_size") or 25),
    )
    groups_payload = list_dedupe_groups(
        session,
        job_id=dedupe_job_id,
        limit=min(max(int(payload.get("group_limit") or 25), 1), 100),
        offset=0,
        strategy=str(payload.get("strategy") or "exact_hash"),
        min_group_size=2,
    )
    task.progress_json = _dumps(
        {
            **progress,
            "dedupe_job_id": dedupe_job_id,
            "dedupe_status": continued.get("status"),
            "groups_found": continued.get("groups_found"),
        }
    )
    if str(continued.get("status")) != "complete":
        task.result_json = _dumps(
            {
                "dedupe_job_id": dedupe_job_id,
                "continued": True,
                "groups": groups_payload.get("groups", []),
                "job": continued,
            }
        )
        task.updated_at = _utc_now()
        session.commit()
        payload_result = _serialize_task(task)
        payload_result["message"] = "Processed a bounded dedupe-analysis task chunk."
        return payload_result
    return {
        "dedupe_job_id": dedupe_job_id,
        "groups": groups_payload.get("groups", []),
        "job": continued,
    }


def _run_apply_dedupe_group(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    return apply_dedupe_group(
        session,
        dedupe_group_id=str(payload.get("dedupe_group_id") or ""),
        keep_file_id=int(payload.get("keep_file_id") or 0),
        move_to_backup_file_ids=[
            int(item) for item in payload.get("move_to_backup_file_ids", []) if int(item) > 0
        ],
        dry_run=bool(payload.get("dry_run", True)),
        actor="queued-task",
    )


def _run_restore_change_set(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    return restore_change_set(
        change_set_id=str(payload.get("change_set_id") or ""),
        actor="queued-task",
        session=session,
    )


def _dispatch_task(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    if task.task_type == TASK_TYPE_CHATGPT_FIRST_FILE_NOTE:
        return _run_chatgpt_first_file_note(session, task=task)
    if task.task_type == TASK_TYPE_SEARCH_NOTES:
        return _run_search_notes(session, task=task)
    if task.task_type == TASK_TYPE_FALLBACK_FILE_NOTE:
        return _run_fallback_file_note(session, task=task)
    if task.task_type == TASK_TYPE_DEDUPE_ANALYSIS:
        return _run_dedupe_analysis(session, task=task)
    if task.task_type == TASK_TYPE_APPLY_DEDUPE_GROUP:
        return _run_apply_dedupe_group(session, task=task)
    if task.task_type == TASK_TYPE_RESTORE_CHANGE_SET:
        return _run_restore_change_set(session, task=task)
    raise FileMutationPolicyError("Unsupported cloud-vault task type.")


def continue_cloud_vault_task(session: Session, *, task_id: str) -> dict[str, object]:
    task = _load_task_by_public_id(session, task_id=task_id)
    if task.status == TASK_STATUS_COMPLETED:
        payload = _serialize_task(task)
        payload["message"] = "Cloud-vault task is already complete."
        return payload
    if task.status == TASK_STATUS_CANCELED:
        payload = _serialize_task(task)
        payload["message"] = "Cloud-vault task was canceled."
        return payload
    task.status = TASK_STATUS_RUNNING
    task.started_at = task.started_at or _utc_now()
    task.heartbeat_at = _utc_now()
    task.updated_at = _utc_now()
    session.commit()
    try:
        result_payload = _dispatch_task(session, task=task)
    except Exception as exc:
        return _mark_task_failed(session, task=task, message=str(exc))
    if task.status in {TASK_STATUS_RUNNING, TASK_STATUS_QUEUED} and task.task_type in {
        TASK_TYPE_SEARCH_NOTES,
        TASK_TYPE_DEDUPE_ANALYSIS,
    }:
        progress = _loads_object(task.progress_json)
        still_running = (
            task.task_type == TASK_TYPE_SEARCH_NOTES
            and int(progress.get("cursor") or 0) < len(progress.get("matched_file_ids", []))
        ) or (
            task.task_type == TASK_TYPE_DEDUPE_ANALYSIS
            and str(progress.get("dedupe_status") or "") != "complete"
        )
        if still_running:
            task.status = TASK_STATUS_RUNNING
            task.updated_at = _utc_now()
            session.commit()
            payload = _serialize_task(task)
            payload["message"] = "Cloud-vault task remains in progress."
            return payload
    return _mark_task_completed(session, task=task, result_payload=result_payload)


def continue_cloud_vault_task_queue(
    session: Session,
    *,
    limit: int = 5,
) -> dict[str, object]:
    task_rows = session.scalars(
        select(CloudVaultTask)
        .where(CloudVaultTask.status.in_([TASK_STATUS_QUEUED, TASK_STATUS_RUNNING]))
        .order_by(CloudVaultTask.priority.asc(), CloudVaultTask.created_at.asc())
        .limit(min(max(limit, 1), 25))
    ).all()
    results = [continue_cloud_vault_task(session, task_id=task.task_id) for task in task_rows]
    return {
        "processed_count": len(results),
        "results": results,
    }


def get_cloud_vault_task_status(session: Session, *, task_id: str) -> dict[str, object]:
    return _serialize_task(_load_task_by_public_id(session, task_id=task_id))


def list_cloud_vault_tasks(
    session: Session,
    *,
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, object]:
    statement = select(CloudVaultTask)
    if status:
        statement = statement.where(CloudVaultTask.status == status)
    if task_type:
        statement = statement.where(CloudVaultTask.task_type == task_type)
    rows = session.scalars(
        statement.order_by(CloudVaultTask.updated_at.desc(), CloudVaultTask.id.desc())
        .offset(offset)
        .limit(min(max(limit, 1), 100))
    ).all()
    return {
        "tasks": [_serialize_task(task) for task in rows],
        "count": len(rows),
    }


def cancel_cloud_vault_task(session: Session, *, task_id: str) -> dict[str, object]:
    task = _load_task_by_public_id(session, task_id=task_id)
    if task.status == TASK_STATUS_COMPLETED:
        raise FileMutationPolicyError("Completed tasks cannot be canceled.")
    task.status = TASK_STATUS_CANCELED
    task.canceled_at = _utc_now()
    task.updated_at = _utc_now()
    session.commit()
    payload = _serialize_task(task)
    payload["message"] = "Cloud-vault task canceled."
    return payload


def collect_cloud_vault_task_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(CloudVaultTask.status, func.count())
        .group_by(CloudVaultTask.status)
    ).all()
    return {str(status): int(count) for status, count in rows if isinstance(status, str)}


def build_default_task_idempotency_key(*, task_type: str, payload: dict[str, object]) -> str:
    return sha256(f"{task_type}|{_dumps(payload)}".encode("utf-8")).hexdigest()
