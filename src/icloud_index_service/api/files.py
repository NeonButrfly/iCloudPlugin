from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from icloud_index_service.api.security import require_plugin_api_token
from icloud_index_service.db import get_session
from icloud_index_service.services.file_access_service import (
    get_file_note_details,
    get_file_source_details,
    resolve_file_source_path,
)
from icloud_index_service.services.file_mutation_service import (
    FileMutationPolicyError,
    FileNamespace,
    create_document_vault_note,
    delete_file_by_path,
    get_change_set_record,
    restore_change_set,
)
from icloud_index_service.services.workflow_index_service import (
    analyze_duplicate_groups,
    get_dedupe_group,
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


class SyncManualFeedbackEventsRequest(BaseModel):
    limit: int = 25


class AnalyzeDuplicateGroupsRequest(BaseModel):
    namespaces: list[str]
    limit: int = 25


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
