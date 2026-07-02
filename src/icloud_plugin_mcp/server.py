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
    ExcerptMaxChars,
    FileId,
    HydrateLimit,
    CanonicalSourcePath,
    ChangeSetId,
    NoteMaxChars,
    NamespaceName,
    PathScope,
    RelativeFolder,
    RelativePath,
    SearchLimit,
    SearchQuery,
    SummaryText,
    VisibleTitle,
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
    canonical_source_path: CanonicalSourcePath,
    attach_originals: bool = True,
) -> dict[str, Any]:
    """Create a structured Obsidian note in document_vault using the categorizer-compatible note contract."""
    with build_service_client_from_env() as client:
        return client.create_document_vault_note(
            relative_folder=relative_folder,
            visible_title=visible_title,
            summary=summary,
            canonical_source_path=canonical_source_path,
            attach_originals=attach_originals,
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
