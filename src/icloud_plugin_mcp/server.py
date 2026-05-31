from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from .service_client import build_service_client_from_env
from .tool_schemas import (
    DEFAULT_EXCERPT_MAX_CHARS,
    DEFAULT_HYDRATE_LIMIT,
    DEFAULT_NOTE_MAX_CHARS,
    DEFAULT_SEARCH_LIMIT,
    ExcerptMaxChars,
    FileId,
    HydrateLimit,
    NoteMaxChars,
    PathScope,
    SearchLimit,
    SearchQuery,
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


@mcp.tool()
def search_icloud_files(
    query: SearchQuery,
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT,
    path_scope: PathScope = None,
) -> dict[str, Any]:
    """Search indexed iCloud Drive files through the local index service."""
    with build_service_client_from_env() as client:
        return client.search_files(query=query, limit=limit, path_scope=path_scope)


@mcp.tool()
def get_icloud_file(file_id: FileId) -> dict[str, Any]:
    """Return indexed metadata and extracted content for a single iCloud Drive file."""
    with build_service_client_from_env() as client:
        return client.get_file(file_id=file_id)


@mcp.tool()
def get_icloud_file_excerpt(
    file_id: FileId,
    max_chars: ExcerptMaxChars = DEFAULT_EXCERPT_MAX_CHARS,
) -> dict[str, Any]:
    """Return file details with locally trimmed content text for lighter responses."""
    with build_service_client_from_env() as client:
        return client.get_file_excerpt(file_id=file_id, max_chars=max_chars)


@mcp.tool()
def get_icloud_note(
    file_id: FileId,
    max_chars: NoteMaxChars = DEFAULT_NOTE_MAX_CHARS,
) -> dict[str, Any]:
    """Return generated note content and note-layer metadata for a single indexed file."""
    with build_service_client_from_env() as client:
        return client.get_file_note(file_id=file_id, max_chars=max_chars)


@mcp.tool()
def get_icloud_source_reference(file_id: FileId) -> dict[str, Any]:
    """Return canonical source-path, source-link, and download-handoff metadata for a file."""
    with build_service_client_from_env() as client:
        return client.get_file_source(file_id=file_id)


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def refresh_icloud_index() -> dict[str, Any]:
    """Queue an iCloud Drive metadata refresh on the backing service."""
    with build_service_client_from_env() as client:
        return client.refresh_index()


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
