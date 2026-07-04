from __future__ import annotations

from collections.abc import Generator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from icloud_index_service.api.security import require_plugin_api_token
from icloud_index_service.db import get_session
from icloud_index_service.services.cloud_vault_task_service import (
    TASK_TYPE_APPLY_DEDUPE_GROUP,
    TASK_TYPE_CHATGPT_FIRST_FILE_NOTE,
    TASK_TYPE_DEDUPE_ANALYSIS,
    TASK_TYPE_EXTERNAL_DATA_NOTE,
    TASK_TYPE_FALLBACK_FILE_NOTE,
    TASK_TYPE_IMPORT_SERVER_FILE,
    TASK_TYPE_IMPORT_SERVER_FOLDER,
    TASK_TYPE_REFRESH_INDEX,
    TASK_TYPE_REINDEX_NOTES,
    TASK_TYPE_RESTORE_CHANGE_SET,
    TASK_TYPE_SEARCH_NOTES,
    TASK_TYPE_SYNC_FEEDBACK,
    cancel_cloud_vault_task,
    continue_cloud_vault_task,
    continue_cloud_vault_task_queue,
    get_cloud_vault_task_status,
    list_cloud_vault_tasks,
    queue_cloud_vault_task,
)
from icloud_index_service.services.file_access_service import (
    get_file_note_details,
    get_file_source_details,
    resolve_file_source_path,
)
from icloud_index_service.services.file_mutation_service import (
    batch_classify_files_and_create_document_vault_notes_fallback,
    classify_file_and_create_document_vault_note_fallback,
    FileMutationPolicyError,
    FileNamespace,
    create_document_vault_note,
    delete_file_by_path,
    get_change_set_record,
    restore_change_set,
    search_files_and_create_document_vault_notes_fallback,
)
from icloud_index_service.services.dedupe_workflow_service import (
    apply_dedupe_group,
    analyze_duplicate_groups,
    continue_dedupe_job,
    get_dedupe_job_status,
    get_dedupe_group,
    list_dedupe_groups,
    start_dedupe_job,
)
from icloud_index_service.services.workflow_index_service import (
    sync_manual_feedback_events,
)
from icloud_index_service.services.search_service import (
    build_database_unavailable_detail,
    get_file_details,
)

router = APIRouter(prefix="/files", tags=["files"])


class DeleteFileRequest(BaseModel):
    namespace: FileNamespace
    relative_path: str


class RestoreChangeSetRequest(BaseModel):
    change_set_id: str


class CreateDocumentVaultNoteRequest(BaseModel):
    relative_folder: str
    visible_title: str
    summary: str
    file_id: int | None = None
    canonical_source_path: str | None = None
    attach_originals: bool = True


FallbackReason = Literal[
    "chatgpt_payload_blocked",
    "chatgpt_note_write_failed",
    "server_500",
    "manual_fallback",
    "other",
]


class ClassifyDocumentVaultNoteFallbackRequest(BaseModel):
    file_id: int
    fallback_reason: FallbackReason = "manual_fallback"
    force_reclassify: bool = False
    summary_mode: Literal["minimal", "classifier", "full_note"] = "classifier"
    title_mode: Literal["generic", "source_name", "classifier"] = "classifier"
    attach_originals: bool = True
    idempotency_key: str | None = None


class BatchClassifyDocumentVaultNotesFallbackRequest(BaseModel):
    file_ids: list[int]
    fallback_reason: FallbackReason = "manual_fallback"
    force_reclassify: bool = False
    summary_mode: Literal["minimal", "classifier", "full_note"] = "classifier"
    title_mode: Literal["generic", "source_name", "classifier"] = "classifier"
    attach_originals: bool = True
    skip_existing: bool = False
    limit: int | None = None


class SearchDocumentVaultNotesFallbackRequest(BaseModel):
    query: str
    path_scope: str | None = None
    namespace: Literal["icloud", "google1", "google2", "local", "uploads"] | None = None
    limit: int = 10
    fallback_reason: FallbackReason = "manual_fallback"
    force_reclassify: bool = False
    skip_existing: bool = False
    summary_mode: Literal["minimal", "classifier", "full_note"] = "classifier"
    title_mode: Literal["generic", "source_name", "classifier"] = "classifier"


class SyncManualFeedbackEventsRequest(BaseModel):
    limit: int = 25


class AnalyzeDuplicateGroupsRequest(BaseModel):
    namespaces: list[str]
    limit: int = 25


class StartDedupeJobRequest(BaseModel):
    namespaces: list[Literal["google1", "google2", "icloud", "document_vault"]] | None = None
    path_scope: str | None = None
    strategy: Literal["exact_hash", "normalized_name_size", "content_hash", "all"] = "exact_hash"
    chunk_size: int | None = None
    max_groups: int | None = None
    dry_run: bool = True


class ContinueDedupeJobRequest(BaseModel):
    job_id: str
    max_runtime_seconds: int | None = None
    chunk_size: int | None = None


class ListDedupeGroupsRequest(BaseModel):
    job_id: str | None = None
    limit: int = 25
    offset: int = 0
    strategy: Literal["exact_hash", "normalized_name_size", "content_hash", "all"] | None = None
    min_group_size: int = 2


class ApplyDedupeGroupRequest(BaseModel):
    dedupe_group_id: str
    keep_file_id: int
    move_to_backup_file_ids: list[int]
    dry_run: bool = True


class QueueCloudVaultTaskRequest(BaseModel):
    task_type: str
    input: dict[str, object]
    idempotency_key: str | None = None
    priority: int = 100


class ContinueCloudVaultTaskRequest(BaseModel):
    task_id: str
    max_runtime_seconds: int | None = None
    chunk_size: int | None = None


class ContinueCloudVaultTaskQueueRequest(BaseModel):
    limit: int = 5
    max_tasks: int | None = None
    task_types: list[str] | None = None


class ListCloudVaultTasksRequest(BaseModel):
    status: str | None = None
    task_type: str | None = None
    limit: int = 25
    offset: int = 0


class CancelCloudVaultTaskRequest(BaseModel):
    task_id: str


class QueueCreateDocumentVaultNoteFromFileIdChatgptFirstRequest(BaseModel):
    file_id: int
    chatgpt_relative_folder: str | None = None
    chatgpt_visible_title: str | None = None
    chatgpt_summary: str | None = None
    fallback_enabled: bool = False
    fallback_reason: FallbackReason = "manual_fallback"
    fallback_summary_mode: Literal["minimal", "classifier", "full_note"] = "classifier"
    fallback_title_mode: Literal["generic", "source_name", "classifier"] = "classifier"
    attach_originals: bool = True
    index_after_create: bool = False
    idempotency_key: str | None = None
    priority: int = 100


class QueueCreateDocumentVaultNotesFromSearchRequest(BaseModel):
    query: str
    path_scope: str | None = None
    namespace: Literal["icloud", "google1", "google2", "document_vault", "local", "uploads"] | None = None
    limit: int = 10
    note_mode: Literal["chatgpt_first", "classifier_fallback", "minimal"] = "minimal"
    fallback_enabled: bool = False
    index_after_create: bool = False
    idempotency_key: str | None = None
    priority: int = 100


class QueueClassifierFallbackNoteFromFileIdRequest(BaseModel):
    file_id: int
    fallback_reason: FallbackReason = "manual_fallback"
    force_reclassify: bool = False
    summary_mode: Literal["minimal", "classifier", "full_note"] = "classifier"
    title_mode: Literal["generic", "source_name", "classifier"] = "classifier"
    attach_originals: bool = True
    index_after_create: bool = False
    idempotency_key: str | None = None
    priority: int = 100


class QueueCreateDocumentVaultNoteFromExternalDataRequest(BaseModel):
    visible_title: str
    relative_folder: str | None = None
    external_source_name: str | None = None
    external_source_type: Literal[
        "chatgpt", "manual", "project_kay", "semester", "school",
        "work", "web", "technical", "personal", "other"
    ] = "chatgpt"
    content: str
    summary: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None
    index_after_create: bool = False
    idempotency_key: str | None = None
    priority: int = 100


class QueueImportServerFileToCloudVaultRequest(BaseModel):
    server_path: str
    destination_folder: str | None = None
    namespace: Literal["uploads", "local"] = "uploads"
    copy_mode: Literal["copy", "move"] = "copy"
    index_after_import: bool = True
    create_note_after_import: bool = False
    note_mode: Literal["chatgpt_first", "classifier_fallback", "minimal"] = "minimal"
    idempotency_key: str | None = None
    priority: int = 100


class QueueImportServerFolderToCloudVaultRequest(BaseModel):
    server_folder: str
    destination_folder: str | None = None
    namespace: Literal["uploads", "local"] = "uploads"
    copy_mode: Literal["copy", "move"] = "copy"
    recursive: bool = True
    include_globs: list[str] | None = None
    exclude_globs: list[str] | None = None
    index_after_import: bool = True
    create_notes_after_import: bool = False
    note_mode: Literal["chatgpt_first", "classifier_fallback", "minimal"] = "minimal"
    chunk_size: int | None = None
    idempotency_key: str | None = None
    priority: int = 100


class QueueRefreshCloudVaultIndexRequest(BaseModel):
    namespaces: list[Literal["icloud", "google1", "google2", "document_vault", "local", "uploads"]] | None = None
    path_scope: str | None = None
    full: bool = False
    extract_text: bool = False
    update_notes_index: bool = False
    idempotency_key: str | None = None
    priority: int = 100


class QueueReindexDocumentVaultNotesRequest(BaseModel):
    path_scope: str | None = None
    limit: int = 25
    idempotency_key: str | None = None
    priority: int = 100


class QueueSyncManualFeedbackEventsRequest(BaseModel):
    limit: int = 25
    idempotency_key: str | None = None
    priority: int = 100


class QueueDedupeAnalysisRequest(BaseModel):
    namespaces: list[Literal["google1", "google2", "icloud", "document_vault", "uploads", "local"]] | None = None
    path_scope: str | None = None
    strategy: Literal["exact_hash", "normalized_name_size", "content_hash", "all"] = "exact_hash"
    chunk_size: int | None = None
    max_groups: int | None = None
    group_limit: int | None = None
    dry_run: bool = True
    max_runtime_seconds: int | None = None
    idempotency_key: str | None = None
    priority: int = 100


class QueueApplyDedupeGroupRequest(BaseModel):
    dedupe_group_id: str
    keep_file_id: int
    move_to_backup_file_ids: list[int]
    dry_run: bool = True
    idempotency_key: str | None = None
    priority: int = 100


class QueueRestoreCloudVaultChangeSetRequest(BaseModel):
    change_set_id: str
    idempotency_key: str | None = None
    priority: int = 100


def _ensure_files_database_available(request: Request) -> None:
    database_healthcheck = getattr(request.app.state, "database_healthcheck", None)
    database_state = getattr(request.app.state, "database_startup_status", None)
    if callable(database_healthcheck):
        try:
            database_state = "ok" if database_healthcheck() else "unavailable"
        except Exception:
            database_state = "unavailable"

    if database_state == "ok":
        return

    startup_validation_error = getattr(request.app.state, "database_startup_error", None)
    raise HTTPException(
        status_code=503,
        detail=build_database_unavailable_detail(
            operation="files",
            startup_validation_error=startup_validation_error,
        ),
    )


def _get_files_session(
    session: Session = Depends(get_session),
) -> Generator[Session, None, None]:
    try:
        yield session
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


@router.get(
    "/{file_id}",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def get_file(
    file_id: int,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        payload = get_file_details(session, file_id=file_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="files",
                startup_validation_error=str(exc),
            ),
        ) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="File not found")
    return payload


@router.get(
    "/{file_id}/note",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def get_file_note(
    file_id: int,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        payload = get_file_note_details(session, file_id=file_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="files",
                startup_validation_error=str(exc),
            ),
        ) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="File not found")
    return payload


@router.get(
    "/{file_id}/source",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def get_file_source(
    file_id: int,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        payload = get_file_source_details(session, file_id=file_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="files",
                startup_validation_error=str(exc),
            ),
        ) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="File not found")
    return payload


@router.get(
    "/{file_id}/source/download",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def download_file_source(
    file_id: int,
    session: Session = Depends(_get_files_session),
) -> FileResponse:
    try:
        source_path = resolve_file_source_path(session, file_id=file_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="files",
                startup_validation_error=str(exc),
            ),
        ) from exc
    if source_path is None:
        raise HTTPException(status_code=404, detail="Source file not found")
    return FileResponse(
        path=source_path,
        filename=source_path.name,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/ops/delete",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def delete_file_route(
    payload: DeleteFileRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return delete_file_by_path(
            namespace=payload.namespace,
            relative_path=payload.relative_path,
            actor="plugin-api",
            session=session,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/restore",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def restore_change_set_route(
    payload: RestoreChangeSetRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return restore_change_set(
            change_set_id=payload.change_set_id,
            actor="plugin-api",
            session=session,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/ops/document-vault/note",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def create_document_vault_note_route(
    payload: CreateDocumentVaultNoteRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    if payload.file_id is None and not payload.canonical_source_path:
        raise HTTPException(
            status_code=400,
            detail="Either file_id or canonical_source_path is required.",
        )
    try:
        return create_document_vault_note(
            relative_folder=payload.relative_folder,
            visible_title=payload.visible_title,
            summary=payload.summary,
            file_id=payload.file_id,
            canonical_source_path=payload.canonical_source_path,
            attach_originals=payload.attach_originals,
            actor="plugin-api",
            session=session,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/document-vault/note/fallback",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def classify_document_vault_note_fallback_route(
    payload: ClassifyDocumentVaultNoteFallbackRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return classify_file_and_create_document_vault_note_fallback(
            file_id=payload.file_id,
            fallback_reason=payload.fallback_reason,
            force_reclassify=payload.force_reclassify,
            summary_mode=payload.summary_mode,
            title_mode=payload.title_mode,
            attach_originals=payload.attach_originals,
            idempotency_key=payload.idempotency_key,
            actor="plugin-api",
            session=session,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/document-vault/note/fallback/batch",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def batch_classify_document_vault_notes_fallback_route(
    payload: BatchClassifyDocumentVaultNotesFallbackRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return batch_classify_files_and_create_document_vault_notes_fallback(
            file_ids=payload.file_ids,
            fallback_reason=payload.fallback_reason,
            force_reclassify=payload.force_reclassify,
            summary_mode=payload.summary_mode,
            title_mode=payload.title_mode,
            attach_originals=payload.attach_originals,
            skip_existing=payload.skip_existing,
            limit=payload.limit,
            actor="plugin-api",
            session=session,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/document-vault/note/fallback/search",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def search_document_vault_notes_fallback_route(
    payload: SearchDocumentVaultNotesFallbackRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return search_files_and_create_document_vault_notes_fallback(
            query=payload.query,
            path_scope=payload.path_scope,
            namespace=payload.namespace,
            limit=payload.limit,
            fallback_reason=payload.fallback_reason,
            force_reclassify=payload.force_reclassify,
            skip_existing=payload.skip_existing,
            summary_mode=payload.summary_mode,
            title_mode=payload.title_mode,
            actor="plugin-api",
            session=session,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/ops/change-sets/{change_set_id}",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def get_change_set_route(
    change_set_id: str,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    payload = get_change_set_record(session, change_set_id=change_set_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    return payload


@router.post(
    "/ops/manual-feedback/sync",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def sync_manual_feedback_events_route(
    payload: SyncManualFeedbackEventsRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return sync_manual_feedback_events(session, limit=payload.limit)


@router.post(
    "/ops/dedupe/analyze",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def analyze_duplicate_groups_route(
    payload: AnalyzeDuplicateGroupsRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return analyze_duplicate_groups(
        session,
        namespaces=payload.namespaces,
        limit=payload.limit,
    )


@router.post(
    "/ops/dedupe/jobs/start",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def start_dedupe_job_route(
    payload: StartDedupeJobRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return start_dedupe_job(
            session,
            namespaces=list(payload.namespaces) if payload.namespaces is not None else None,
            path_scope=payload.path_scope,
            strategy=payload.strategy,
            chunk_size=payload.chunk_size,
            max_groups=payload.max_groups,
            dry_run=payload.dry_run,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/dedupe/jobs/continue",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def continue_dedupe_job_route(
    payload: ContinueDedupeJobRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return continue_dedupe_job(
            session,
            job_id=payload.job_id,
            max_runtime_seconds=payload.max_runtime_seconds,
            chunk_size=payload.chunk_size,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/ops/dedupe/jobs/{job_id}",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def get_dedupe_job_status_route(
    job_id: str,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return get_dedupe_job_status(session, job_id=job_id)
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/ops/dedupe/groups/list",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def list_dedupe_groups_route(
    payload: ListDedupeGroupsRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return list_dedupe_groups(
            session,
            job_id=payload.job_id,
            limit=payload.limit,
            offset=payload.offset,
            strategy=payload.strategy,
            min_group_size=payload.min_group_size,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/ops/dedupe/groups/{dedupe_group_id}",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def get_dedupe_group_route(
    dedupe_group_id: str,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    payload = get_dedupe_group(session, dedupe_group_id=dedupe_group_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Dedupe group not found")
    return payload


@router.post(
    "/ops/dedupe/groups/apply",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def apply_dedupe_group_route(
    payload: ApplyDedupeGroupRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return apply_dedupe_group(
            session,
            dedupe_group_id=payload.dedupe_group_id,
            keep_file_id=payload.keep_file_id,
            move_to_backup_file_ids=payload.move_to_backup_file_ids,
            dry_run=payload.dry_run,
            actor="plugin-api",
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/tasks/queue",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_cloud_vault_task_route(
    payload: QueueCloudVaultTaskRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return queue_cloud_vault_task(
            session,
            task_type=payload.task_type,
            input_payload=payload.input,
            idempotency_key=payload.idempotency_key,
            priority=payload.priority,
        )
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/tasks/continue",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def continue_cloud_vault_task_route(
    payload: ContinueCloudVaultTaskRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return continue_cloud_vault_task(session, task_id=payload.task_id)
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/ops/tasks/continue-queue",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def continue_cloud_vault_task_queue_route(
    payload: ContinueCloudVaultTaskQueueRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return continue_cloud_vault_task_queue(
        session,
        limit=payload.max_tasks or payload.limit,
        task_types=payload.task_types,
    )


@router.get(
    "/ops/tasks/{task_id}",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def get_cloud_vault_task_status_route(
    task_id: str,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return get_cloud_vault_task_status(session, task_id=task_id)
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/ops/tasks/list",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def list_cloud_vault_tasks_route(
    payload: ListCloudVaultTasksRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return list_cloud_vault_tasks(
        session,
        status=payload.status,
        task_type=payload.task_type,
        limit=payload.limit,
        offset=payload.offset,
    )


@router.post(
    "/ops/tasks/cancel",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def cancel_cloud_vault_task_route(
    payload: CancelCloudVaultTaskRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        return cancel_cloud_vault_task(session, task_id=payload.task_id)
    except FileMutationPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ops/tasks/document-vault/note/file-id/chatgpt-first",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_create_document_vault_note_from_file_id_chatgpt_first_route(
    payload: QueueCreateDocumentVaultNoteFromFileIdChatgptFirstRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_CHATGPT_FIRST_FILE_NOTE,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/document-vault/notes/search",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_create_document_vault_notes_from_search_route(
    payload: QueueCreateDocumentVaultNotesFromSearchRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_SEARCH_NOTES,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/document-vault/note/fallback/file-id",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_classifier_fallback_note_from_file_id_route(
    payload: QueueClassifierFallbackNoteFromFileIdRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_FALLBACK_FILE_NOTE,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/document-vault/note/external-data",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_create_document_vault_note_from_external_data_route(
    payload: QueueCreateDocumentVaultNoteFromExternalDataRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_EXTERNAL_DATA_NOTE,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/imports/file",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_import_server_file_to_cloud_vault_route(
    payload: QueueImportServerFileToCloudVaultRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_IMPORT_SERVER_FILE,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/imports/folder",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_import_server_folder_to_cloud_vault_route(
    payload: QueueImportServerFolderToCloudVaultRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_IMPORT_SERVER_FOLDER,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/index/refresh",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_refresh_cloud_vault_index_route(
    payload: QueueRefreshCloudVaultIndexRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_REFRESH_INDEX,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/document-vault/reindex",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_reindex_document_vault_notes_route(
    payload: QueueReindexDocumentVaultNotesRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_REINDEX_NOTES,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/manual-feedback/sync",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_sync_manual_feedback_events_route(
    payload: QueueSyncManualFeedbackEventsRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_SYNC_FEEDBACK,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/dedupe/analyze",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_dedupe_analysis_route(
    payload: QueueDedupeAnalysisRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_DEDUPE_ANALYSIS,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/dedupe/groups/apply",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_apply_icloud_dedupe_group_route(
    payload: QueueApplyDedupeGroupRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_APPLY_DEDUPE_GROUP,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )


@router.post(
    "/ops/tasks/restore",
    dependencies=[Depends(_ensure_files_database_available), Depends(require_plugin_api_token)],
)
def queue_restore_icloud_change_set_route(
    payload: QueueRestoreCloudVaultChangeSetRequest,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    return queue_cloud_vault_task(
        session,
        task_type=TASK_TYPE_RESTORE_CHANGE_SET,
        input_payload=payload.model_dump(exclude={"idempotency_key", "priority"}),
        idempotency_key=payload.idempotency_key,
        priority=payload.priority,
    )
