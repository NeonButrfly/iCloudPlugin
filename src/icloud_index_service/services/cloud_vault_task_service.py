from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from icloud_index_service.models.cloud_vault_task import CloudVaultTask
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.classification_submission import (
    get_mcp_fallback_classification_enabled,
)
from icloud_index_service.services.dedupe_workflow_service import (
    apply_dedupe_group,
    continue_dedupe_job,
    list_dedupe_groups,
    start_dedupe_job,
)
from icloud_index_service.services.file_mutation_service import (
    FileNamespace,
    FileMutationPolicyError,
    classify_file_and_create_document_vault_note_fallback,
    create_document_vault_note_from_external_data,
    create_document_vault_note,
    import_server_file_to_cloud_vault,
    normalize_relative_folder,
    resolve_namespace_root,
    restore_change_set,
)
from icloud_index_service.services.job_runner import enqueue_metadata_refresh
from icloud_index_service.services.search_service import search_files
from icloud_index_service.services.workflow_index_service import (
    reindex_document_vault_notes,
    sync_manual_feedback_events,
)

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELED = "canceled"

TASK_TYPE_CHATGPT_FIRST_FILE_NOTE = "create_document_vault_note_from_file_id_chatgpt_first"
TASK_TYPE_SEARCH_NOTES = "create_document_vault_notes_from_search"
TASK_TYPE_FALLBACK_FILE_NOTE = "classifier_fallback_note_from_file_id"
TASK_TYPE_EXTERNAL_DATA_NOTE = "create_document_vault_note_from_external_data"
TASK_TYPE_IMPORT_SERVER_FILE = "import_server_file_to_cloud_vault"
TASK_TYPE_IMPORT_SERVER_FOLDER = "import_server_folder_to_cloud_vault"
TASK_TYPE_REFRESH_INDEX = "refresh_cloud_vault_index"
TASK_TYPE_REINDEX_NOTES = "reindex_document_vault_notes"
TASK_TYPE_SYNC_FEEDBACK = "sync_manual_feedback_events"
TASK_TYPE_DEDUPE_ANALYSIS = "dedupe_analysis"
TASK_TYPE_APPLY_DEDUPE_GROUP = "apply_dedupe_group"
TASK_TYPE_RESTORE_CHANGE_SET = "restore_change_set"

SUPPORTED_TASK_TYPES = {
    TASK_TYPE_CHATGPT_FIRST_FILE_NOTE,
    TASK_TYPE_SEARCH_NOTES,
    TASK_TYPE_FALLBACK_FILE_NOTE,
    TASK_TYPE_EXTERNAL_DATA_NOTE,
    TASK_TYPE_IMPORT_SERVER_FILE,
    TASK_TYPE_IMPORT_SERVER_FOLDER,
    TASK_TYPE_REFRESH_INDEX,
    TASK_TYPE_REINDEX_NOTES,
    TASK_TYPE_SYNC_FEEDBACK,
    TASK_TYPE_DEDUPE_ANALYSIS,
    TASK_TYPE_APPLY_DEDUPE_GROUP,
    TASK_TYPE_RESTORE_CHANGE_SET,
}

DEFAULT_IMPORT_NOTE_FOLDER = "00 Inbox/ChatGPT Imports"
DEFAULT_CLOUD_VAULT_TASK_WORKER_ENABLED = True
DEFAULT_CLOUD_VAULT_TASK_WORKER_LIMIT = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_cloud_vault_task_worker_enabled() -> bool:
    raw_value = str(
        os.getenv("CLOUD_VAULT_TASK_WORKER_ENABLED", str(DEFAULT_CLOUD_VAULT_TASK_WORKER_ENABLED))
    ).strip().lower()
    return raw_value not in {"0", "false", "no", "off"}


def get_cloud_vault_task_worker_limit() -> int:
    raw_value = os.getenv("CLOUD_VAULT_TASK_WORKER_LIMIT")
    if raw_value is None:
        return DEFAULT_CLOUD_VAULT_TASK_WORKER_LIMIT
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_CLOUD_VAULT_TASK_WORKER_LIMIT
    return min(max(parsed_value, 1), 25)


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


def _resolve_import_namespace(raw_value: object) -> FileNamespace:
    value = str(raw_value or FileNamespace.UPLOADS.value).strip().lower()
    if value not in {FileNamespace.LOCAL.value, FileNamespace.UPLOADS.value}:
        raise FileMutationPolicyError("Only the local and uploads namespaces are supported for imports.")
    return FileNamespace(value)


def _reindex_scope_for_note_path(note_path: str | None) -> str | None:
    if not note_path:
        return None
    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
    try:
        relative_parent = Path(str(note_path)).resolve().parent.relative_to(vault_root.resolve())
    except ValueError:
        return None
    return relative_parent.as_posix() if relative_parent.parts else None


def _maybe_reindex_note_result(
    session: Session,
    *,
    result: dict[str, object],
    enabled: bool,
    limit: int = 200,
) -> None:
    if not enabled:
        return
    note_scope = _reindex_scope_for_note_path(str(result.get("note_path") or "") or None)
    result["reindex"] = reindex_document_vault_notes(
        session,
        path_scope=note_scope,
        limit=limit,
    )


def _schedule_refresh_job(session: Session) -> dict[str, object]:
    refresh_job = enqueue_metadata_refresh(session)
    return {
        "refresh_job_id": refresh_job.id,
        "refresh_status": refresh_job.status,
    }


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
        result = create_document_vault_note(
            relative_folder=relative_folder,
            visible_title=visible_title,
            summary=summary,
            file_id=file_id,
            attach_originals=attach_originals,
            actor="queued-task",
            session=session,
        )
        _maybe_reindex_note_result(
            session,
            result=result,
            enabled=bool(payload.get("index_after_create")),
        )
        return result
    except FileMutationPolicyError:
        if not fallback_enabled:
            raise
        result = classify_file_and_create_document_vault_note_fallback(
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
        _maybe_reindex_note_result(
            session,
            result=result,
            enabled=bool(payload.get("index_after_create")),
        )
        return result


def _run_external_data_note(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    visible_title = str(payload.get("visible_title") or "").strip()
    content = str(payload.get("content") or "")
    if not visible_title:
        raise FileMutationPolicyError("visible_title is required.")
    if not content.strip():
        raise FileMutationPolicyError("content is required.")
    result = create_document_vault_note_from_external_data(
        visible_title=visible_title,
        relative_folder=str(payload.get("relative_folder") or "") or None,
        external_source_name=str(payload.get("external_source_name") or "") or None,
        external_source_type=str(payload.get("external_source_type") or "chatgpt"),
        content=content,
        summary=str(payload.get("summary") or "") or None,
        tags=[
            str(item).strip()
            for item in payload.get("tags", [])
            if str(item).strip()
        ]
        if isinstance(payload.get("tags"), list)
        else None,
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
        actor="queued-task",
        idempotency_key=task.idempotency_key,
        session=session,
    )
    _maybe_reindex_note_result(
        session,
        result=result,
        enabled=bool(payload.get("index_after_create")),
    )
    return result


def _maybe_create_import_note(
    session: Session,
    *,
    file_id: int,
    note_mode: str,
    destination_folder: str | None,
) -> dict[str, object] | None:
    if note_mode == "classifier_fallback":
        if not get_mcp_fallback_classification_enabled():
            raise FileMutationPolicyError("Classifier fallback mode is not enabled.")
        return classify_file_and_create_document_vault_note_fallback(
            file_id=file_id,
            fallback_reason="manual_fallback",
            attach_originals=True,
            actor="queued-task",
            session=session,
        )

    file_record = session.get(FileRecord, file_id)
    if file_record is None:
        return None
    note_folder = normalize_relative_folder(
        destination_folder,
        default_folder=DEFAULT_IMPORT_NOTE_FOLDER,
    )
    return create_document_vault_note(
        relative_folder=note_folder,
        visible_title=_derive_note_title(file_record=file_record),
        summary=_derive_note_summary(file_record=file_record),
        file_id=file_id,
        attach_originals=True,
        actor="queued-task",
        session=session,
    )


def _run_import_server_file(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    import_result = import_server_file_to_cloud_vault(
        server_path=str(payload.get("server_path") or ""),
        destination_folder=str(payload.get("destination_folder") or "") or None,
        namespace=_resolve_import_namespace(payload.get("namespace")),
        copy_mode=str(payload.get("copy_mode") or "copy"),
        actor="queued-task",
        session=session,
    )
    if bool(payload.get("create_note_after_import")):
        import_result["note_result"] = _maybe_create_import_note(
            session,
            file_id=int(import_result["file_id"]),
            note_mode=str(payload.get("note_mode") or "minimal"),
            destination_folder=str(payload.get("destination_folder") or "") or None,
        )
        _maybe_reindex_note_result(
            session,
            result=import_result["note_result"],
            enabled=bool(payload.get("index_after_import")),
        )
    if bool(payload.get("index_after_import")):
        import_result["refresh"] = _schedule_refresh_job(session)
    return import_result


def _run_import_server_folder(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    from fnmatch import fnmatch
    from icloud_index_service.services.file_mutation_service import _validate_allowed_import_path

    payload = _loads_object(task.input_json)
    progress = _loads_object(task.progress_json)
    if not progress:
        folder_path = _validate_allowed_import_path(
            str(payload.get("server_folder") or ""),
            expect_directory=True,
        )
        recursive = bool(payload.get("recursive", True))
        include_globs = [
            str(item).strip() for item in payload.get("include_globs", []) if str(item).strip()
        ] if isinstance(payload.get("include_globs"), list) else []
        exclude_globs = [
            str(item).strip() for item in payload.get("exclude_globs", []) if str(item).strip()
        ] if isinstance(payload.get("exclude_globs"), list) else []
        pattern = "**/*" if recursive else "*"
        matched_files: list[str] = []
        for candidate in sorted(folder_path.glob(pattern)):
            if not candidate.is_file():
                continue
            relative_name = candidate.relative_to(folder_path).as_posix()
            if include_globs and not any(fnmatch(relative_name, glob) for glob in include_globs):
                continue
            if exclude_globs and any(fnmatch(relative_name, glob) for glob in exclude_globs):
                continue
            matched_files.append(str(candidate))
        progress = {
            "matched_files": matched_files,
            "cursor": 0,
            "results": [],
        }

    matched_files = [str(item) for item in progress.get("matched_files", []) if str(item).strip()]
    cursor = int(progress.get("cursor") or 0)
    chunk_size = min(max(int(payload.get("chunk_size") or 10), 1), 25)
    results = list(progress.get("results") or [])
    for item in matched_files[cursor : cursor + chunk_size]:
        import_result = import_server_file_to_cloud_vault(
            server_path=item,
            destination_folder=str(payload.get("destination_folder") or "") or None,
            namespace=_resolve_import_namespace(payload.get("namespace")),
            copy_mode=str(payload.get("copy_mode") or "copy"),
            actor="queued-task",
            session=session,
        )
        if bool(payload.get("create_notes_after_import")):
            import_result["note_result"] = _maybe_create_import_note(
                session,
                file_id=int(import_result["file_id"]),
                note_mode=str(payload.get("note_mode") or "minimal"),
                destination_folder=str(payload.get("destination_folder") or "") or None,
            )
        results.append(import_result)
    cursor += len(matched_files[cursor : cursor + chunk_size])
    completed = cursor >= len(matched_files)
    post_processing: dict[str, object] = {}
    if completed and bool(payload.get("index_after_import")):
        post_processing["refresh"] = _schedule_refresh_job(session)
        if bool(payload.get("create_notes_after_import")):
            post_processing["reindex"] = reindex_document_vault_notes(session, limit=200)
    task.progress_json = _dumps(
        {
            "matched_files": matched_files,
            "cursor": cursor,
            "results": results,
            "matched_count": len(matched_files),
            "processed_count": cursor,
            **({"post_processing": post_processing} if post_processing else {}),
        }
    )
    task.updated_at = _utc_now()
    task.heartbeat_at = _utc_now()
    session.commit()
    return {
        "matched_count": len(matched_files),
        "processed_count": cursor,
        "results": results,
        **post_processing,
    }


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
    completed = cursor >= len(file_ids)
    post_processing: dict[str, object] = {}
    if completed and bool(payload.get("index_after_create")):
        post_processing["reindex"] = reindex_document_vault_notes(session, limit=200)
    task.progress_json = _dumps(
        {
            **progress,
            "matched_file_ids": file_ids,
            "cursor": cursor,
            "results": results,
            "matched_count": len(file_ids),
            "processed_count": len(results),
            **({"post_processing": post_processing} if post_processing else {}),
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
        **post_processing,
    }


def _run_fallback_file_note(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    result = classify_file_and_create_document_vault_note_fallback(
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
    _maybe_reindex_note_result(
        session,
        result=result,
        enabled=bool(payload.get("index_after_create")),
    )
    return result


def _run_refresh_index(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    del task
    return {
        **_schedule_refresh_job(session),
        "message": "Refresh job queued.",
    }


def _run_reindex_notes(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    return reindex_document_vault_notes(
        session,
        path_scope=str(payload.get("path_scope") or "") or None,
        limit=min(max(int(payload.get("limit") or 25), 1), 200),
    )


def _run_sync_feedback(session: Session, *, task: CloudVaultTask) -> dict[str, object]:
    payload = _loads_object(task.input_json)
    return sync_manual_feedback_events(
        session,
        limit=min(max(int(payload.get("limit") or 25), 1), 200),
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
    if task.task_type == TASK_TYPE_EXTERNAL_DATA_NOTE:
        return _run_external_data_note(session, task=task)
    if task.task_type == TASK_TYPE_IMPORT_SERVER_FILE:
        return _run_import_server_file(session, task=task)
    if task.task_type == TASK_TYPE_IMPORT_SERVER_FOLDER:
        return _run_import_server_folder(session, task=task)
    if task.task_type == TASK_TYPE_REFRESH_INDEX:
        return _run_refresh_index(session, task=task)
    if task.task_type == TASK_TYPE_REINDEX_NOTES:
        return _run_reindex_notes(session, task=task)
    if task.task_type == TASK_TYPE_SYNC_FEEDBACK:
        return _run_sync_feedback(session, task=task)
    if task.task_type == TASK_TYPE_DEDUPE_ANALYSIS:
        return _run_dedupe_analysis(session, task=task)
    if task.task_type == TASK_TYPE_APPLY_DEDUPE_GROUP:
        return _run_apply_dedupe_group(session, task=task)
    if task.task_type == TASK_TYPE_RESTORE_CHANGE_SET:
        return _run_restore_change_set(session, task=task)
    raise FileMutationPolicyError("Unsupported cloud-vault task type.")


def _task_type_filter(task_types: list[str] | None) -> list[str]:
    if not task_types:
        return []
    return [item for item in task_types if item in SUPPORTED_TASK_TYPES]


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
    task.error_message = None
    task.completed_at = None
    task.canceled_at = None
    task.started_at = task.started_at or _utc_now()
    task.heartbeat_at = _utc_now()
    task.updated_at = _utc_now()
    session.commit()
    try:
        result_payload = _dispatch_task(session, task=task)
    except Exception as exc:
        session.rollback()
        task = _load_task_by_public_id(session, task_id=task_id)
        return _mark_task_failed(session, task=task, message=str(exc))
    if task.status in {TASK_STATUS_RUNNING, TASK_STATUS_QUEUED} and task.task_type in {
        TASK_TYPE_SEARCH_NOTES,
        TASK_TYPE_IMPORT_SERVER_FOLDER,
        TASK_TYPE_DEDUPE_ANALYSIS,
    }:
        progress = _loads_object(task.progress_json)
        still_running = (
            task.task_type == TASK_TYPE_SEARCH_NOTES
            and int(progress.get("cursor") or 0) < len(progress.get("matched_file_ids", []))
        ) or (
            task.task_type == TASK_TYPE_IMPORT_SERVER_FOLDER
            and int(progress.get("cursor") or 0) < len(progress.get("matched_files", []))
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
    task_types: list[str] | None = None,
) -> dict[str, object]:
    statement = (
        select(CloudVaultTask)
        .where(CloudVaultTask.status.in_([TASK_STATUS_QUEUED, TASK_STATUS_RUNNING]))
        .order_by(CloudVaultTask.priority.asc(), CloudVaultTask.created_at.asc())
    )
    filtered_task_types = _task_type_filter(task_types)
    if task_types and not filtered_task_types:
        return {
            "processed_count": 0,
            "results": [],
            "remaining_count": 0,
        }
    if filtered_task_types:
        statement = statement.where(CloudVaultTask.task_type.in_(filtered_task_types))
    task_rows = session.scalars(statement.limit(min(max(limit, 1), 25))).all()
    results = [continue_cloud_vault_task(session, task_id=task.task_id) for task in task_rows]
    remaining_statement = select(func.count()).select_from(CloudVaultTask).where(
        CloudVaultTask.status.in_([TASK_STATUS_QUEUED, TASK_STATUS_RUNNING])
    )
    if filtered_task_types:
        remaining_statement = remaining_statement.where(
            CloudVaultTask.task_type.in_(filtered_task_types)
        )
    remaining_count = int(session.scalar(remaining_statement) or 0)
    return {
        "processed_count": len(results),
        "results": results,
        "remaining_count": remaining_count,
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
