from __future__ import annotations

import argparse
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
def get_icloud_dedupe_group(dedupe_group_id: DedupeGroupId) -> dict[str, Any]:
    """Return indexed metadata and member items for a duplicate-group proposal."""
    with build_service_client_from_env() as client:
        return client.get_dedupe_group(dedupe_group_id=dedupe_group_id)


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
    """Analyze live mirrored files for duplicate candidates and persist indexed duplicate-group proposals."""
    with build_service_client_from_env() as client:
        return client.analyze_duplicate_groups(namespaces=namespaces, limit=limit)


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
