from __future__ import annotations

from typing import Annotated

from pydantic import Field

DEFAULT_SEARCH_LIMIT = 5
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
