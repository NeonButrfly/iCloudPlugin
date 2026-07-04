from __future__ import annotations

import argparse
import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .service_client import build_service_client_from_env
from .tool_schemas import (
    DEFAULT_EXCERPT_MAX_CHARS,
    DEFAULT_HYDRATE_LIMIT,
    DEFAULT_NOTE_MAX_CHARS,
    DEFAULT_SEARCH_LIMIT,
    ChangeSetId,
    DedupeJobId,
    DedupeStrategy,
    DedupeGroupId,
    ExcerptMaxChars,
    FallbackReason,
    FileId,
    FileIdList,
    HydrateLimit,
    NoteMaxChars,
    NamespaceName,
    NamespaceList,
    OptionalCanonicalSourcePath,
    OptionalFileId,
    OptionalText,
    PathScope,
    RelativeFolder,
    RelativePath,
    SearchLimit,
    SearchQuery,
    SummaryMode,
    SummaryText,
    TaskId,
    TaskStatus,
    TaskType,
    TitleMode,
    VisibleTitle,
    WorkflowLimit,
)

mcp = FastMCP(
    name="iCloud Drive",
    instructions=(
        "Thin MCP proxy for a local iCloud index service. Use these tools to search "
        "indexed iCloud Drive files, inspect file details, fetch trimmed excerpts, "
        "and trigger a metadata refresh."
    ),
    json_response=True,
)

READ_ONLY_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    destructiveHint=False,
)

WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    openWorldHint=False,
    destructiveHint=False,
)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def search_icloud_files(
    query: SearchQuery,
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT,
    path_scope: PathScope = None,
) -> dict[str, Any]:
    """Search indexed iCloud Drive files through the local index service."""
    with build_service_client_from_env() as client:
        return client.search_files(query=query, limit=limit, path_scope=path_scope)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_file(file_id: FileId) -> dict[str, Any]:
    """Return indexed metadata and extracted content for a single iCloud Drive file."""
    with build_service_client_from_env() as client:
        return client.get_file(file_id=file_id)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_file_excerpt(
    file_id: FileId,
    max_chars: ExcerptMaxChars = DEFAULT_EXCERPT_MAX_CHARS,
) -> dict[str, Any]:
    """Return file details with locally trimmed content text for lighter responses."""
    with build_service_client_from_env() as client:
        return client.get_file_excerpt(file_id=file_id, max_chars=max_chars)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_note(
    file_id: FileId,
    max_chars: NoteMaxChars = DEFAULT_NOTE_MAX_CHARS,
) -> dict[str, Any]:
    """Return generated note content and note-layer metadata for a single indexed file."""
    with build_service_client_from_env() as client:
        return client.get_file_note(file_id=file_id, max_chars=max_chars)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_source_reference(file_id: FileId) -> dict[str, Any]:
    """Return canonical source-path, source-link, and download-handoff metadata for a file."""
    with build_service_client_from_env() as client:
        return client.get_file_source(file_id=file_id)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_file_bundle(
    file_id: FileId,
    max_chars: ExcerptMaxChars = DEFAULT_EXCERPT_MAX_CHARS,
    note_max_chars: NoteMaxChars = DEFAULT_NOTE_MAX_CHARS,
) -> dict[str, Any]:
    """Return file metadata, trimmed source excerpt, generated note content, and source-reference metadata together."""
    with build_service_client_from_env() as client:
        file_payload = client.get_file_excerpt(file_id=file_id, max_chars=max_chars)
        note_payload = client.get_file_note(file_id=file_id, max_chars=note_max_chars)
        source_payload = client.get_file_source(file_id=file_id)
    return {
        "file": file_payload,
        "note": note_payload,
        "source": source_payload,
    }


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def search_icloud_notes_and_files(
    query: SearchQuery,
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT,
    path_scope: PathScope = None,
    hydrate_limit: HydrateLimit = DEFAULT_HYDRATE_LIMIT,
    max_chars: ExcerptMaxChars = DEFAULT_EXCERPT_MAX_CHARS,
    note_max_chars: NoteMaxChars = DEFAULT_NOTE_MAX_CHARS,
) -> dict[str, Any]:
    """Search files, then expand the top matches into note-plus-source bundles for quicker analysis."""
    with build_service_client_from_env() as client:
        return client.search_notes_and_files(
            query=query,
            limit=limit,
            path_scope=path_scope,
            hydrate_limit=hydrate_limit,
            max_chars=max_chars,
            note_max_chars=note_max_chars,
        )


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_system_status() -> dict[str, Any]:
    """Return live cloud-vault health, refresh progress, classifier readiness, and queue counts."""
    with build_service_client_from_env() as client:
        return client.get_system_status()


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_product_readiness() -> dict[str, Any]:
    """Return a consolidated product-readiness report showing what is complete versus blocked."""
    with build_service_client_from_env() as client:
        return client.get_product_readiness()


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_change_set(change_set_id: ChangeSetId) -> dict[str, Any]:
    """Return indexed metadata and item history for a reversible change set."""
    with build_service_client_from_env() as client:
        return client.get_change_set(change_set_id=change_set_id)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_cloud_vault_task_status(task_id: TaskId) -> dict[str, Any]:
    """Return persisted status, progress, and result metadata for a cloud-vault task."""
    with build_service_client_from_env() as client:
        return client.get_cloud_vault_task_status(task_id=task_id)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def list_cloud_vault_tasks(
    status: TaskStatus = None,
    task_type: TaskType = None,
    limit: WorkflowLimit = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List queued, running, completed, failed, or canceled cloud-vault tasks."""
    with build_service_client_from_env() as client:
        return client.list_cloud_vault_tasks(
            status=status,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_dedupe_group(dedupe_group_id: DedupeGroupId) -> dict[str, Any]:
    """Return indexed metadata and member items for a duplicate-group proposal."""
    with build_service_client_from_env() as client:
        return client.get_dedupe_group(dedupe_group_id=dedupe_group_id)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def get_icloud_dedupe_job_status(job_id: DedupeJobId) -> dict[str, Any]:
    """Return persisted status and progress for a dedupe job."""
    with build_service_client_from_env() as client:
        return client.get_dedupe_job_status(job_id=job_id)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS, structured_output=True)
def list_icloud_dedupe_groups(
    job_id: DedupeJobId | None = None,
    limit: WorkflowLimit = 25,
    offset: int = 0,
    strategy: DedupeStrategy | None = None,
    min_group_size: int = 2,
) -> dict[str, Any]:
    """Page duplicate-group proposals produced by the resumable dedupe workflow."""
    with build_service_client_from_env() as client:
        return client.list_dedupe_groups(
            job_id=job_id,
            limit=limit,
            offset=offset,
            strategy=strategy,
            min_group_size=min_group_size,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def refresh_icloud_index() -> dict[str, Any]:
    """Queue an iCloud Drive metadata refresh on the backing service."""
    with build_service_client_from_env() as client:
        return client.refresh_index()


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def pause_icloud_index() -> dict[str, Any]:
    """Pause background iCloud Drive metadata refresh work while preserving resumable progress."""
    with build_service_client_from_env() as client:
        return client.pause_index()


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def resume_icloud_index() -> dict[str, Any]:
    """Resume paused iCloud Drive metadata refresh work from the saved frontier."""
    with build_service_client_from_env() as client:
        return client.resume_index()


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def create_document_vault_note(
    relative_folder: RelativeFolder,
    visible_title: VisibleTitle,
    summary: SummaryText,
    file_id: OptionalFileId = None,
    canonical_source_path: OptionalCanonicalSourcePath = None,
    attach_originals: bool = True,
) -> dict[str, Any]:
    """Create a structured Obsidian note in document_vault using the categorizer-compatible note contract."""
    with build_service_client_from_env() as client:
        return client.create_document_vault_note(
            relative_folder=relative_folder,
            visible_title=visible_title,
            summary=summary,
            file_id=file_id,
            canonical_source_path=canonical_source_path,
            attach_originals=attach_originals,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_cloud_vault_task(
    task_type: str,
    input_payload_json: str,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue a generic cloud-vault task when a higher-level wrapper is not sufficient."""
    with build_service_client_from_env() as client:
        return client.queue_cloud_vault_task(
            task_type=task_type,
            input_payload=json.loads(input_payload_json),
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def continue_cloud_vault_task(
    task_id: TaskId,
    max_runtime_seconds: int | None = None,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Advance one cloud-vault task by one bounded server-side execution step."""
    with build_service_client_from_env() as client:
        return client.continue_cloud_vault_task(
            task_id=task_id,
            max_runtime_seconds=max_runtime_seconds,
            chunk_size=chunk_size,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def continue_cloud_vault_task_queue(
    limit: WorkflowLimit = 5,
    max_tasks: int | None = None,
    task_types_json: OptionalText = None,
) -> dict[str, Any]:
    """Advance the next few queued or running cloud-vault tasks in priority order."""
    with build_service_client_from_env() as client:
        return client.continue_cloud_vault_task_queue(
            limit=limit,
            max_tasks=max_tasks,
            task_types=json.loads(task_types_json) if task_types_json else None,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def cancel_cloud_vault_task(task_id: TaskId) -> dict[str, Any]:
    """Cancel a queued or running cloud-vault task before it completes."""
    with build_service_client_from_env() as client:
        return client.cancel_cloud_vault_task(task_id=task_id)


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_create_document_vault_note_from_file_id_chatgpt_first(
    file_id: FileId,
    chatgpt_relative_folder: OptionalText = None,
    chatgpt_visible_title: OptionalText = None,
    chatgpt_summary: OptionalText = None,
    fallback_enabled: bool = False,
    fallback_reason: FallbackReason = "manual_fallback",
    fallback_summary_mode: SummaryMode = "classifier",
    fallback_title_mode: TitleMode = "classifier",
    attach_originals: bool = True,
    index_after_create: bool = False,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue a file-id-based ChatGPT-first note creation task with optional fallback to the local classifier."""
    with build_service_client_from_env() as client:
        return client.queue_create_document_vault_note_from_file_id_chatgpt_first(
            file_id=file_id,
            chatgpt_relative_folder=chatgpt_relative_folder,
            chatgpt_visible_title=chatgpt_visible_title,
            chatgpt_summary=chatgpt_summary,
            fallback_enabled=fallback_enabled,
            fallback_reason=fallback_reason,
            fallback_summary_mode=fallback_summary_mode,
            fallback_title_mode=fallback_title_mode,
            attach_originals=attach_originals,
            index_after_create=index_after_create,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_create_document_vault_notes_from_search(
    query: SearchQuery,
    path_scope: PathScope = None,
    namespace: OptionalText = None,
    limit: WorkflowLimit = 10,
    note_mode: OptionalText = "minimal",
    fallback_enabled: bool = False,
    index_after_create: bool = False,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Search indexed files and queue server-side note creation work for the matching file ids."""
    with build_service_client_from_env() as client:
        return client.queue_create_document_vault_notes_from_search(
            query=query,
            path_scope=path_scope,
            namespace=namespace,
            limit=limit,
            note_mode=str(note_mode or "minimal"),
            fallback_enabled=fallback_enabled,
            index_after_create=index_after_create,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_classifier_fallback_note_from_file_id(
    file_id: FileId,
    fallback_reason: FallbackReason = "manual_fallback",
    force_reclassify: bool = False,
    summary_mode: SummaryMode = "classifier",
    title_mode: TitleMode = "classifier",
    attach_originals: bool = True,
    index_after_create: bool = False,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue explicit file-id-only local-classifier fallback note creation without auto-draining any broader queue."""
    with build_service_client_from_env() as client:
        return client.queue_classifier_fallback_note_from_file_id(
            file_id=file_id,
            fallback_reason=fallback_reason,
            force_reclassify=force_reclassify,
            summary_mode=summary_mode,
            title_mode=title_mode,
            attach_originals=attach_originals,
            index_after_create=index_after_create,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_create_document_vault_note_from_external_data(
    visible_title: VisibleTitle,
    content: SummaryText,
    relative_folder: OptionalText = None,
    external_source_name: OptionalText = None,
    external_source_type: OptionalText = "chatgpt",
    summary: OptionalText = None,
    tags_json: OptionalText = None,
    metadata_json: OptionalText = None,
    index_after_create: bool = False,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue creation of a document_vault note from arbitrary external structured data supplied by ChatGPT."""
    with build_service_client_from_env() as client:
        return client.queue_create_document_vault_note_from_external_data(
            visible_title=visible_title,
            content=content,
            relative_folder=relative_folder,
            external_source_name=external_source_name,
            external_source_type=str(external_source_type or "chatgpt"),
            summary=summary,
            tags=json.loads(tags_json) if tags_json else None,
            metadata=json.loads(metadata_json) if metadata_json else None,
            index_after_create=index_after_create,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_import_server_file_to_cloud_vault(
    server_path: RelativePath,
    destination_folder: OptionalText = None,
    namespace: OptionalText = "uploads",
    copy_mode: OptionalText = "copy",
    index_after_import: bool = True,
    create_note_after_import: bool = False,
    note_mode: OptionalText = "minimal",
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue import of a file already visible to the MCP server under an allowed import root."""
    with build_service_client_from_env() as client:
        return client.queue_import_server_file_to_cloud_vault(
            server_path=server_path,
            destination_folder=destination_folder,
            namespace=str(namespace or "uploads"),
            copy_mode=str(copy_mode or "copy"),
            index_after_import=index_after_import,
            create_note_after_import=create_note_after_import,
            note_mode=str(note_mode or "minimal"),
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_import_server_folder_to_cloud_vault(
    server_folder: RelativePath,
    destination_folder: OptionalText = None,
    namespace: OptionalText = "uploads",
    copy_mode: OptionalText = "copy",
    recursive: bool = True,
    include_globs_json: OptionalText = None,
    exclude_globs_json: OptionalText = None,
    index_after_import: bool = True,
    create_notes_after_import: bool = False,
    note_mode: OptionalText = "minimal",
    chunk_size: int | None = None,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue import of a server-visible folder under an allowed import root while preserving relative structure."""
    with build_service_client_from_env() as client:
        return client.queue_import_server_folder_to_cloud_vault(
            server_folder=server_folder,
            destination_folder=destination_folder,
            namespace=str(namespace or "uploads"),
            copy_mode=str(copy_mode or "copy"),
            recursive=recursive,
            include_globs=json.loads(include_globs_json) if include_globs_json else None,
            exclude_globs=json.loads(exclude_globs_json) if exclude_globs_json else None,
            index_after_import=index_after_import,
            create_notes_after_import=create_notes_after_import,
            note_mode=str(note_mode or "minimal"),
            chunk_size=chunk_size,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_refresh_cloud_vault_index(
    namespaces_json: OptionalText = None,
    path_scope: OptionalText = None,
    full: bool = False,
    extract_text: bool = False,
    update_notes_index: bool = False,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue metadata/index refresh work without triggering automatic classifier execution."""
    with build_service_client_from_env() as client:
        return client.queue_refresh_cloud_vault_index(
            namespaces=json.loads(namespaces_json) if namespaces_json else None,
            path_scope=path_scope,
            full=full,
            extract_text=extract_text,
            update_notes_index=update_notes_index,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_reindex_document_vault_notes(
    path_scope: OptionalText = None,
    limit: WorkflowLimit = 25,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue reindexing of document_vault notes after external note creation or manual edits."""
    with build_service_client_from_env() as client:
        return client.queue_reindex_document_vault_notes(
            path_scope=path_scope,
            limit=limit,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_sync_manual_feedback_events(
    limit: WorkflowLimit = 25,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue manual-feedback event synchronization without coupling it to broader background automation."""
    with build_service_client_from_env() as client:
        return client.queue_sync_manual_feedback_events(
            limit=limit,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_dedupe_analysis(
    namespaces: NamespaceList | None = None,
    path_scope: OptionalText = None,
    strategy: DedupeStrategy = "exact_hash",
    chunk_size: WorkflowLimit = 25,
    max_groups: WorkflowLimit = 25,
    group_limit: WorkflowLimit = 25,
    dry_run: bool = True,
    max_runtime_seconds: int = 15,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue resumable dedupe analysis that advances in bounded chunks instead of timing out inline."""
    with build_service_client_from_env() as client:
        return client.queue_dedupe_analysis(
            namespaces=namespaces,
            path_scope=path_scope,
            strategy=strategy,
            chunk_size=chunk_size,
            max_groups=max_groups,
            group_limit=group_limit,
            dry_run=dry_run,
            max_runtime_seconds=max_runtime_seconds,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_apply_icloud_dedupe_group(
    dedupe_group_id: DedupeGroupId,
    keep_file_id: FileId,
    move_to_backup_file_ids: FileIdList,
    dry_run: bool = True,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue non-destructive dedupe application through reversible _CHANGES_BACKUP storage."""
    with build_service_client_from_env() as client:
        return client.queue_apply_icloud_dedupe_group(
            dedupe_group_id=dedupe_group_id,
            keep_file_id=keep_file_id,
            move_to_backup_file_ids=move_to_backup_file_ids,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def queue_restore_icloud_change_set(
    change_set_id: ChangeSetId,
    idempotency_key: OptionalText = None,
    priority: int = 100,
) -> dict[str, Any]:
    """Queue a reversible change-set restore through the cloud-vault task system."""
    with build_service_client_from_env() as client:
        return client.queue_restore_icloud_change_set(
            change_set_id=change_set_id,
            idempotency_key=idempotency_key,
            priority=priority,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def classify_file_and_create_document_vault_note_fallback(
    file_id: FileId,
    fallback_reason: FallbackReason = "manual_fallback",
    force_reclassify: bool = False,
    summary_mode: SummaryMode = "classifier",
    title_mode: TitleMode = "classifier",
    attach_originals: bool = True,
    idempotency_key: OptionalText = None,
) -> dict[str, Any]:
    """Use the local classifier only as an explicit MCP fallback after normal ChatGPT-authored note creation fails or is blocked."""
    with build_service_client_from_env() as client:
        return client.classify_file_and_create_document_vault_note_fallback(
            file_id=file_id,
            fallback_reason=fallback_reason,
            force_reclassify=force_reclassify,
            summary_mode=summary_mode,
            title_mode=title_mode,
            attach_originals=attach_originals,
            idempotency_key=idempotency_key,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def batch_classify_files_and_create_document_vault_notes_fallback(
    file_ids: FileIdList,
    fallback_reason: FallbackReason = "manual_fallback",
    force_reclassify: bool = False,
    summary_mode: SummaryMode = "classifier",
    title_mode: TitleMode = "classifier",
    attach_originals: bool = True,
    skip_existing: bool = False,
    limit: WorkflowLimit = 25,
) -> dict[str, Any]:
    """Run explicit local-classifier fallback note creation only for the requested indexed file ids."""
    with build_service_client_from_env() as client:
        return client.batch_classify_files_and_create_document_vault_notes_fallback(
            file_ids=file_ids,
            fallback_reason=fallback_reason,
            force_reclassify=force_reclassify,
            summary_mode=summary_mode,
            title_mode=title_mode,
            attach_originals=attach_originals,
            skip_existing=skip_existing,
            limit=limit,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def search_files_and_create_document_vault_notes_fallback(
    query: SearchQuery,
    path_scope: PathScope = None,
    namespace: str | None = None,
    limit: WorkflowLimit = 10,
    fallback_reason: FallbackReason = "manual_fallback",
    force_reclassify: bool = False,
    skip_existing: bool = False,
    summary_mode: SummaryMode = "classifier",
    title_mode: TitleMode = "classifier",
) -> dict[str, Any]:
    """Search indexed files server-side, then invoke the local classifier only for this explicit fallback MCP call."""
    with build_service_client_from_env() as client:
        return client.search_files_and_create_document_vault_notes_fallback(
            query=query,
            path_scope=path_scope,
            namespace=namespace,
            limit=limit,
            fallback_reason=fallback_reason,
            force_reclassify=force_reclassify,
            skip_existing=skip_existing,
            summary_mode=summary_mode,
            title_mode=title_mode,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def delete_icloud_file(
    namespace: NamespaceName,
    relative_path: RelativePath,
) -> dict[str, Any]:
    """Move a live file into the namespace-specific _CHANGES_BACKUP area and return a reversible change set."""
    with build_service_client_from_env() as client:
        return client.delete_file(namespace=namespace, relative_path=relative_path)


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def restore_icloud_change_set(change_set_id: ChangeSetId) -> dict[str, Any]:
    """Restore a previously backed-up change set from _CHANGES_BACKUP."""
    with build_service_client_from_env() as client:
        return client.restore_change_set(change_set_id=change_set_id)


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def sync_icloud_manual_feedback_events(
    limit: WorkflowLimit = 25,
) -> dict[str, Any]:
    """Re-read manual Obsidian feedback signals and persist them as indexed feedback events."""
    with build_service_client_from_env() as client:
        return client.sync_manual_feedback_events(limit=limit)


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def analyze_icloud_duplicates(
    namespaces: NamespaceList,
    limit: WorkflowLimit = 25,
) -> dict[str, Any]:
    """Deprecated synchronous dedupe entrypoint that now creates a resumable dedupe job instead."""
    with build_service_client_from_env() as client:
        return client.analyze_duplicate_groups(namespaces=namespaces, limit=limit)


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def start_icloud_dedupe_job(
    namespaces: NamespaceList | None = None,
    path_scope: OptionalText = None,
    strategy: DedupeStrategy = "exact_hash",
    chunk_size: WorkflowLimit = 25,
    max_groups: WorkflowLimit = 25,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create a resumable dedupe job that returns quickly without scanning the whole vault inline."""
    with build_service_client_from_env() as client:
        return client.start_dedupe_job(
            namespaces=namespaces,
            path_scope=path_scope,
            strategy=strategy,
            chunk_size=chunk_size,
            max_groups=max_groups,
            dry_run=dry_run,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def continue_icloud_dedupe_job(
    job_id: DedupeJobId,
    max_runtime_seconds: int = 15,
    chunk_size: WorkflowLimit = 25,
) -> dict[str, Any]:
    """Continue a dedupe job in bounded chunks so MCP callers can avoid request timeouts."""
    with build_service_client_from_env() as client:
        return client.continue_dedupe_job(
            job_id=job_id,
            max_runtime_seconds=max_runtime_seconds,
            chunk_size=chunk_size,
        )


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def apply_icloud_dedupe_group(
    dedupe_group_id: DedupeGroupId,
    keep_file_id: FileId,
    move_to_backup_file_ids: FileIdList,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply a reviewed dedupe proposal by moving chosen duplicates into _CHANGES_BACKUP with a reversible change set."""
    with build_service_client_from_env() as client:
        return client.apply_dedupe_group(
            dedupe_group_id=dedupe_group_id,
            keep_file_id=keep_file_id,
            move_to_backup_file_ids=move_to_backup_file_ids,
            dry_run=dry_run,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local MCP proxy for the iCloud index service.",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio"],
        help="MCP transport to serve. The local plugin uses stdio.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
