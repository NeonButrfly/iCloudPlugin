from __future__ import annotations

from typing import Annotated

from pydantic import Field

DEFAULT_SEARCH_LIMIT = 5
DEFAULT_HYDRATE_LIMIT = 3
DEFAULT_EXCERPT_MAX_CHARS = 1000
DEFAULT_NOTE_MAX_CHARS = 20_000

SearchQuery = Annotated[
    str,
    Field(
        min_length=1,
        description="Free-text query matched against indexed iCloud Drive file names, paths, and extracted content.",
    ),
]

SearchLimit = Annotated[
    int,
    Field(ge=1, le=50, description="Maximum number of matching files to return."),
]

HydrateLimit = Annotated[
    int,
    Field(
        ge=0,
        le=10,
        description=(
            "How many top search matches should be expanded into note-plus-file bundles."
        ),
    ),
]

PathScope = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "Optional iCloud Drive folder prefix to limit matches. "
            "Accepts either absolute paths like /Finance or relative names like Finance."
        ),
    ),
]

FileId = Annotated[
    int,
    Field(ge=1, description="Numeric file identifier returned by the iCloud index service."),
]

OptionalFileId = Annotated[
    int | None,
    Field(
        default=None,
        ge=1,
        description="Optional numeric file identifier used to resolve the source file server-side.",
    ),
]

ExcerptMaxChars = Annotated[
    int,
    Field(
        ge=1,
        le=10_000,
        description="Maximum number of content characters to keep in the returned excerpt payload.",
    ),
]

NoteMaxChars = Annotated[
    int,
    Field(
        ge=1,
        le=50_000,
        description="Maximum number of note characters to keep in the returned note payload.",
    ),
]

NamespaceName = Annotated[
    str,
    Field(
        pattern="^(google1|google2|icloud|document_vault)$",
        description="Writable vault namespace.",
    ),
]

RelativePath = Annotated[
    str,
    Field(
        min_length=1,
        description="Path relative to the chosen namespace root. Underscore-prefixed paths stay internal-only.",
    ),
]

ChangeSetId = Annotated[
    str,
    Field(min_length=1, description="Opaque reversible change-set identifier."),
]

RelativeFolder = Annotated[
    str,
    Field(
        min_length=1,
        description="Target folder inside document_vault for structured note creation.",
    ),
]

VisibleTitle = Annotated[
    str,
    Field(min_length=1, description="Human-visible note title or source display name."),
]

SummaryText = Annotated[
    str,
    Field(min_length=1, description="Short note summary used in the structured Obsidian note."),
]

CanonicalSourcePath = Annotated[
    str,
    Field(
        min_length=1,
        description="Canonical source file path associated with the structured Obsidian note.",
    ),
]

OptionalCanonicalSourcePath = Annotated[
    str | None,
    Field(
        default=None,
        min_length=1,
        description="Optional canonical source file path retained for backward-compatible note creation calls.",
    ),
]

WorkflowLimit = Annotated[
    int,
    Field(ge=1, le=200, description="Maximum number of records or proposals to process."),
]

NamespaceList = Annotated[
    list[str],
    Field(
        min_length=1,
        description="Namespace list restricted to google1, google2, icloud, and document_vault for dedupe workflows.",
    ),
]

DedupeGroupId = Annotated[
    str,
    Field(min_length=1, description="Indexed duplicate-group identifier."),
]

DedupeJobId = Annotated[
    str,
    Field(min_length=1, description="Persisted dedupe job identifier."),
]

DedupeStrategy = Annotated[
    str,
    Field(
        pattern="^(exact_hash|normalized_name_size|content_hash|all)$",
        description="Duplicate-analysis strategy.",
    ),
]

FallbackReason = Annotated[
    str,
    Field(
        pattern="^(chatgpt_payload_blocked|chatgpt_note_write_failed|server_500|manual_fallback|other)$",
        description="Reason why the explicit local-classifier fallback is being invoked.",
    ),
]

FallbackReasonOptional = Annotated[
    str | None,
    Field(
        default=None,
        pattern="^(chatgpt_payload_blocked|chatgpt_note_write_failed|server_500|manual_fallback|other)$",
        description="Optional reason for invoking the local-classifier fallback path.",
    ),
]

SummaryMode = Annotated[
    str,
    Field(
        pattern="^(minimal|classifier|full_note)$",
        description="Requested summary style for the fallback note path.",
    ),
]

TitleMode = Annotated[
    str,
    Field(
        pattern="^(generic|source_name|classifier)$",
        description="Requested title style for the fallback note path.",
    ),
]

FileIdList = Annotated[
    list[int],
    Field(min_length=1, description="Indexed file identifiers to process through the fallback path."),
]

OptionalText = Annotated[
    str | None,
    Field(default=None, min_length=1, description="Optional free-form idempotency or path-scope string."),
]
