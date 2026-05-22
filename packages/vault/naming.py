from __future__ import annotations

import os
import re
from pathlib import Path


def clean_visible_title(value: str, max_len: int = 120) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", str(value or "document"))
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned[:max_len] or "document"


def _split_name(name: str) -> tuple[str, str]:
    stem, extension = os.path.splitext(name)
    return stem, extension


def ensure_unique_filename(name: str, existing_names: set[str] | None = None) -> str:
    if not existing_names or name not in existing_names:
        return name

    stem, extension = _split_name(name)
    counter = 2
    while True:
        candidate = f"{stem} ({counter}){extension}"
        if candidate not in existing_names:
            return candidate
        counter += 1


def build_note_filename(
    *,
    title: str,
    primary_label: str,
    existing_names: set[str] | None = None,
) -> str:
    base_name = f"{clean_visible_title(title)} - {primary_label}.md"
    return ensure_unique_filename(base_name, existing_names)


def build_extracted_markdown_filename(
    *,
    title: str,
    existing_names: set[str] | None = None,
) -> str:
    base_name = f"{clean_visible_title(title)}.extracted.md"
    return ensure_unique_filename(base_name, existing_names)


def build_attachment_filename(
    *,
    source_name: str,
    existing_names: set[str] | None = None,
) -> str:
    source_path = Path(source_name)
    cleaned_stem = clean_visible_title(source_path.stem)
    base_name = f"{cleaned_stem}{source_path.suffix}"
    return ensure_unique_filename(base_name, existing_names)
