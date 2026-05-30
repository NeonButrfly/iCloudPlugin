from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord

DEFAULT_VAULT_RECONCILIATION_LIMIT = 10
GENERATED_NOTE_ROOTS = ("01 Classified", "02 Needs Review")
MANUAL_NOTE_SKIP_PREFIXES = (".obsidian", "_system")
OWNED_FRONTMATTER_FIELDS = (
    "canonical_source_path",
    "canonical_source_hash",
    "last_seen_filename",
    "attachment_mode",
    "compatibility_attachment_path",
    "source_link",
    "attachment",
    "source_parser",
    "heuristic_primary_hint",
    "hybrid_live_source",
)


def _normalize_folder_token(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    if normalized.endswith("ies") and len(normalized) > 3:
        singular = normalized[:-3] + "y"
        if singular:
            return singular
    if normalized.endswith("s") and len(normalized) > 3 and not normalized.endswith("ss"):
        singular = normalized[:-1]
        if singular:
            return singular
    return normalized


def _read_bool_env(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def get_vault_reconciliation_enabled() -> bool:
    return _read_bool_env("CLASSIFIER_VAULT_RECONCILIATION_ENABLED", default=True)


def get_vault_reconciliation_limit() -> int:
    raw_value = os.getenv("CLASSIFIER_VAULT_RECONCILIATION_LIMIT")
    if raw_value is None:
        return DEFAULT_VAULT_RECONCILIATION_LIMIT
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_VAULT_RECONCILIATION_LIMIT
    return max(parsed_value, 1)


def _resolve_mirror_root() -> Path | None:
    source_mode = (os.getenv("ICLOUD_SOURCE_MODE") or "").strip().lower()
    mirror_root = (os.getenv("ICLOUD_MIRROR_ROOT") or "").strip()
    if source_mode != "filesystem-mirror" or not mirror_root:
        return None
    mirror_root_path = Path(mirror_root).resolve()
    if not mirror_root_path.exists() or not mirror_root_path.is_dir():
        return None
    return mirror_root_path


def _resolve_vault_root() -> Path | None:
    vault_root = (os.getenv("CLASSIFIER_VAULT_ROOT") or "").strip()
    if not vault_root:
        return None
    vault_root_path = Path(vault_root).resolve()
    if not vault_root_path.exists() or not vault_root_path.is_dir():
        return None
    return vault_root_path


def _resolve_note_path(note_path_value: str, vault_root: Path) -> Path:
    if note_path_value.startswith("/vault/"):
        relative_parts = PurePosixPath(note_path_value).parts[2:]
        return (vault_root / Path(*relative_parts)).resolve()

    raw_path = Path(note_path_value)
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (vault_root / note_path_value.lstrip("/\\")).resolve()


def _vault_note_reference(note_path: Path, vault_root: Path) -> str:
    relative_path = note_path.resolve().relative_to(vault_root.resolve())
    return f"/vault/{relative_path.as_posix()}"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], list[str], int] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return None

    values: dict[str, str] = {}
    for line in lines[1:end_index]:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed_value = raw_value.strip("'\"")
        if isinstance(parsed_value, str):
            values[key] = parsed_value
    return values, lines, end_index


def _update_frontmatter_fields(note_text: str, updates: dict[str, str]) -> str:
    parsed = _parse_frontmatter(note_text)
    if parsed is None:
        return note_text

    _, lines, end_index = parsed
    field_indexes: dict[str, int] = {}
    for index in range(1, end_index):
        line = lines[index]
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip()
        field_indexes[key] = index

    insertion_index = end_index
    for key in OWNED_FRONTMATTER_FIELDS:
        if key not in updates:
            continue
        serialized_line = f"{key}: {json.dumps(updates[key], ensure_ascii=False)}"
        existing_index = field_indexes.get(key)
        if existing_index is not None:
            lines[existing_index] = serialized_line
            continue
        lines.insert(insertion_index, serialized_line)
        insertion_index += 1

    return "\n".join(lines) + ("\n" if note_text.endswith("\n") else "")


def _first_non_empty_string(*values: object) -> str:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return ""


def _extract_nested_string(payload: dict[str, object], *path: str) -> str:
    current: object = payload
    for part in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return _first_non_empty_string(current)


def _build_state_note_metadata(
    state: ClassificationState,
    *,
    manifest_record: dict[str, object],
) -> dict[str, str]:
    response_payload = _parse_json_object(state.response_payload_json)
    response_record = response_payload.get("record")
    if not isinstance(response_record, dict):
        response_record = {}

    source_parser = _first_non_empty_string(
        manifest_record.get("source_parser"),
        response_record.get("source_parser"),
        _extract_nested_string(manifest_record, "timing", "parser"),
        _extract_nested_string(response_record, "timing", "parser"),
    )
    hybrid_live_source = _first_non_empty_string(
        manifest_record.get("hybrid_live_source"),
        response_record.get("hybrid_live_source"),
        _extract_nested_string(manifest_record, "timing", "hybrid_live_source"),
        _extract_nested_string(response_record, "timing", "hybrid_live_source"),
        _extract_nested_string(manifest_record, "hybrid", "decision", "live_source"),
        _extract_nested_string(response_record, "hybrid", "decision", "live_source"),
    )
    heuristic_primary_hint = _first_non_empty_string(
        manifest_record.get("heuristic_primary_hint"),
        response_record.get("heuristic_primary_hint"),
        _extract_nested_string(manifest_record, "timing", "heuristic_primary_hint"),
        _extract_nested_string(response_record, "timing", "heuristic_primary_hint"),
    )
    if not heuristic_primary_hint and hybrid_live_source == "heuristic-fast-path":
        heuristic_primary_hint = _first_non_empty_string(
            _extract_nested_string(manifest_record, "hybrid", "decision", "selected_primary_hint"),
            _extract_nested_string(response_record, "hybrid", "decision", "selected_primary_hint"),
            _extract_nested_string(manifest_record, "classification", "primary_label"),
            _extract_nested_string(response_record, "classification", "primary_label"),
            _first_non_empty_string(state.primary_label),
        )
    if not heuristic_primary_hint and source_parser:
        heuristic_primary_hint = "unknown"

    return {
        "canonical_source_path": _first_non_empty_string(
            manifest_record.get("canonical_source_path"),
            response_record.get("canonical_source_path"),
        ),
        "canonical_source_hash": _first_non_empty_string(
            manifest_record.get("canonical_source_hash"),
            response_record.get("canonical_source_hash"),
        ),
        "last_seen_filename": _first_non_empty_string(
            manifest_record.get("last_seen_filename"),
            response_record.get("last_seen_filename"),
        ),
        "attachment_mode": _first_non_empty_string(
            manifest_record.get("attachment_mode"),
            response_record.get("attachment_mode"),
        ),
        "compatibility_attachment_path": _first_non_empty_string(
            manifest_record.get("compatibility_attachment_path"),
            response_record.get("compatibility_attachment_path"),
        ),
        "source_link": _first_non_empty_string(
            manifest_record.get("source_link"),
            response_record.get("source_link"),
        ),
        "source_parser": source_parser,
        "heuristic_primary_hint": heuristic_primary_hint,
        "hybrid_live_source": hybrid_live_source,
    }


def _merge_note_metadata(
    note_metadata: dict[str, str],
    *,
    state_metadata: dict[str, str],
) -> dict[str, str]:
    merged = dict(note_metadata)
    for field_name, state_value in state_metadata.items():
        if field_name in note_metadata and str(note_metadata.get(field_name, "")).strip():
            continue
        if not state_value:
            continue
        merged[field_name] = state_value
    return merged


def _build_canonical_source_link(canonical_source_path: str | None, display_name: str) -> str:
    if not canonical_source_path:
        return ""

    source_path = canonical_source_path.strip().replace("\\", "/")
    if not source_path:
        return ""

    cloud_vault_prefix = "/srv/cloud-vault/"
    if source_path.startswith(cloud_vault_prefix):
        relative_path = source_path[len(cloud_vault_prefix):]
        base_target = os.getenv(
            "CLASSIFIER_SOURCE_LINK_BASE_URL",
            r"\\192.168.50.86\cloud-vault",
        ).strip()
        if base_target.startswith("\\\\"):
            normalized_base = base_target.rstrip("\\/")
            target = normalized_base + "\\" + relative_path.replace("/", "\\")
        elif re.match(r"^[A-Za-z]:[/\\]", base_target):
            normalized_base = base_target.rstrip("\\/")
            target = normalized_base + "\\" + relative_path.replace("/", "\\")
        else:
            target = f"{base_target.rstrip('/')}/{relative_path}"
    elif source_path.startswith("/"):
        target = f"file://{source_path}"
    elif re.match(r"^[A-Za-z]:/", source_path):
        target = f"file:///{source_path}"
    else:
        target = f"file://{source_path}"

    label = display_name.replace("]", r"\]")
    return f"[{label}](<{target}>)"


def _update_original_file_section(note_text: str, replacement: str) -> str:
    pattern = re.compile(
        r"(## Original File\s*\n\s*\n)(.*?)(\n## Extracted Markdown File\s*\n)",
        re.DOTALL,
    )

    def _replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{replacement}{match.group(3)}"

    updated_text, count = pattern.subn(_replace, note_text, count=1)
    return updated_text if count else note_text


def _repair_note_links(note_text: str, metadata: dict[str, str]) -> tuple[str, bool]:
    canonical_source_path = metadata.get("canonical_source_path", "")
    last_seen_filename = metadata.get("last_seen_filename", "")
    attachment_mode = metadata.get("attachment_mode", "none")
    compatibility_attachment_path = metadata.get("compatibility_attachment_path", "")
    if (
        attachment_mode != "canonical-source-link"
        and "source_link" not in metadata
        and "attachment" not in metadata
        and "## Original File" not in note_text
    ):
        return note_text, False
    source_link = _build_canonical_source_link(canonical_source_path, last_seen_filename)
    attachment_value = (
        source_link
        if attachment_mode == "canonical-source-link"
        else compatibility_attachment_path
    )
    updated_text = _update_frontmatter_fields(
        note_text,
        {
            "canonical_source_path": canonical_source_path,
            "canonical_source_hash": metadata.get("canonical_source_hash", ""),
            "last_seen_filename": last_seen_filename,
            "attachment_mode": attachment_mode,
            "compatibility_attachment_path": compatibility_attachment_path,
            "source_link": source_link,
            "attachment": attachment_value,
            "source_parser": metadata.get("source_parser", ""),
            "heuristic_primary_hint": metadata.get("heuristic_primary_hint", ""),
            "hybrid_live_source": metadata.get("hybrid_live_source", ""),
        },
    )

    replacement = (
        attachment_value
        if attachment_value
        else "Original file was not copied into the vault. Re-run with `--attach-originals` if desired."
    )
    updated_text = _update_original_file_section(updated_text, replacement)
    return updated_text, updated_text != note_text


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _note_suffix_rank(name: str) -> tuple[int, int]:
    match = re.search(r" \((\d+)\)\.md$", name)
    if match is None:
        return (0, 0)
    return (1, int(match.group(1)))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_live_candidates(session: Session, mirror_root: Path) -> list[tuple[FileRecord, Path]]:
    candidates: list[tuple[FileRecord, Path]] = []
    records = session.scalars(
        select(FileRecord)
        .where(FileRecord.is_deleted.is_(False))
        .order_by(FileRecord.id.asc())
    ).all()
    for file_record in records:
        candidate_path = (mirror_root / file_record.path.lstrip("/")).resolve()
        if candidate_path.exists() and candidate_path.is_file():
            candidates.append((file_record, candidate_path))
    return candidates


def _iter_generated_notes(vault_root: Path) -> list[tuple[Path, dict[str, str]]]:
    notes: list[tuple[Path, dict[str, str]]] = []
    for root_name in GENERATED_NOTE_ROOTS:
        note_root = vault_root / root_name
        if not note_root.exists():
            continue
        for note_path in note_root.rglob("*.md"):
            parsed = _parse_frontmatter(
                note_path.read_text(encoding="utf-8", errors="replace")
            )
            if parsed is None:
                continue
            metadata, _, _ = parsed
            if metadata.get("type") != "classified-document":
                continue
            notes.append((note_path.resolve(), metadata))
    return notes


def _load_vault_folder_label_map(folder_label_map_path: Path | None) -> dict[str, dict[str, object]]:
    if folder_label_map_path is None or not folder_label_map_path.exists():
        return {}
    try:
        loaded = json.loads(folder_label_map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}

    normalized: dict[str, dict[str, object]] = {}
    for raw_key, raw_value in loaded.items():
        key_parts = [_normalize_folder_token(part) for part in str(raw_key).split("/") if _normalize_folder_token(part)]
        if not key_parts:
            continue
        normalized_key = "/".join(key_parts)
        if isinstance(raw_value, str):
            normalized[normalized_key] = {
                "primary_label": raw_value,
                "secondary_labels": [],
            }
            continue
        if not isinstance(raw_value, dict):
            continue
        normalized[normalized_key] = {
            "primary_label": str(raw_value.get("primary_label", "")).strip(),
            "secondary_labels": [
                str(item).strip()
                for item in (raw_value.get("secondary_labels", []) or [])
                if str(item).strip()
            ],
        }
    return normalized


def _build_known_label_aliases(known_labels: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for label in known_labels:
        label_text = str(label).strip()
        if not label_text:
            continue
        aliases.setdefault(label_text, label_text)
        normalized = _normalize_folder_token(label_text)
        if normalized:
            aliases.setdefault(normalized, label_text)
            if not normalized.endswith("s"):
                aliases.setdefault(f"{normalized}s", label_text)
            if normalized.endswith("y"):
                aliases.setdefault(f"{normalized[:-1]}ies", label_text)
    return aliases


def _extract_frontmatter_list(note_text: str, field_name: str) -> list[str]:
    parsed = _parse_frontmatter(note_text)
    if parsed is None:
        return []
    _, lines, end_index = parsed
    for index in range(1, end_index):
        line = lines[index]
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        if key.strip() != field_name:
            continue
        try:
            parsed_value = json.loads(raw_value.strip())
        except json.JSONDecodeError:
            return []
        if isinstance(parsed_value, list):
            return [str(item).strip() for item in parsed_value if str(item).strip()]
        return []
    return []


def _expected_generated_category_parts(note_text: str, metadata: dict[str, str]) -> list[str]:
    primary_label = str(metadata.get("primary_label", "")).strip().lower()
    secondary_labels = [item.lower() for item in _extract_frontmatter_list(note_text, "secondary_labels")]
    if primary_label == "medical" and {"appeal", "appeals"} & set(secondary_labels):
        return ["medical", "appeals"]
    return [primary_label] if primary_label else []


def _infer_label_from_folder_parts(
    folder_parts: list[str],
    *,
    known_label_aliases: dict[str, str],
    folder_label_map: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    normalized_parts = [_normalize_folder_token(part) for part in folder_parts if _normalize_folder_token(part)]
    if not normalized_parts:
        return None

    for start_index in range(len(normalized_parts)):
        candidate_key = "/".join(normalized_parts[start_index:])
        mapped = folder_label_map.get(candidate_key)
        if mapped:
            primary_label = str(mapped.get("primary_label", "")).strip()
            if primary_label:
                return {
                    "primary_label": primary_label,
                    "secondary_labels": [
                        str(item).strip()
                        for item in (mapped.get("secondary_labels", []) or [])
                        if str(item).strip()
                    ],
                    "match_source": "explicit-folder-map",
                    "matched_folder_key": candidate_key,
                }

    matched_labels: list[str] = []
    seen: set[str] = set()
    for part in reversed(normalized_parts):
        mapped_label = known_label_aliases.get(part)
        if not mapped_label or mapped_label in seen:
            continue
        matched_labels.append(mapped_label)
        seen.add(mapped_label)

    if not matched_labels:
        return None

    return {
        "primary_label": matched_labels[0],
        "secondary_labels": matched_labels[1:3],
        "match_source": "derived-folder-label",
        "matched_folder_key": normalized_parts[-1],
    }


def _manual_feedback_entry(
    *,
    vault_root: Path,
    note_path: Path,
    metadata: dict[str, str],
    note_text: str,
    known_labels: list[str],
    known_label_aliases: dict[str, str],
    folder_label_map: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    relative_path = note_path.relative_to(vault_root)
    relative_parts = list(relative_path.parts)
    if not relative_parts or relative_parts[0] in MANUAL_NOTE_SKIP_PREFIXES:
        return None

    folder_parts = relative_parts[:-1]
    generated_root = relative_parts[0] if relative_parts[0] in GENERATED_NOTE_ROOTS else ""
    generated_folder_parts = folder_parts[1:] if generated_root else folder_parts
    folder_hint = _infer_label_from_folder_parts(
        generated_folder_parts,
        known_label_aliases=known_label_aliases,
        folder_label_map=folder_label_map,
    )

    explicit_primary = str(metadata.get("primary_label", "")).strip()
    explicit_secondary = _extract_frontmatter_list(note_text, "secondary_labels")
    heading = ""
    for line in note_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            break
    summary = heading or note_path.stem

    is_generated_note = str(metadata.get("type", "")).strip() == "classified-document"
    if is_generated_note:
        expected_parts = _expected_generated_category_parts(note_text, metadata)
        path_matches_generated_default = bool(generated_root) and generated_folder_parts == expected_parts
        review_action = str(metadata.get("recommended_action", "")).strip().lower()
        moved_between_review_states = (
            (generated_root == "01 Classified" and review_action == "review")
            or (generated_root == "02 Needs Review" and review_action not in {"", "review"})
        )
        if path_matches_generated_default and not moved_between_review_states:
            return None

        source_path = (
            metadata.get("canonical_source_path", "")
            or metadata.get("source_file", "")
            or note_path.as_posix()
        )
        correct_label = (
            str((folder_hint or {}).get("primary_label", "")).strip()
            or explicit_primary
        )
        if not correct_label:
            return None
        old_label = explicit_primary or "unknown"
        if old_label and correct_label == old_label:
            return None
        generated_context = _derive_generated_note_feedback_context(
            source_path_text=source_path,
            metadata=metadata,
            known_labels=known_labels,
        )
        secondary_labels = [
            str(item).strip()
            for item in ((folder_hint or {}).get("secondary_labels", []) or [])
            if str(item).strip()
        ]
        review_status = "manual-note-move"
        note_summary = f"manual-note-move:{relative_path.as_posix()}"
        return {
            "state_key": f"generated:{source_path}",
            "source_path": source_path,
            "filename": Path(source_path).name or note_path.name,
            "source_filename": note_path.name,
            "correct_label": correct_label,
            "old_label": old_label,
            "secondary_labels": secondary_labels,
            "summary": summary,
            "note": note_summary,
            "parser": str(generated_context.get("parser", "")).strip() or "obsidian-generated-note",
            "heuristic_primary": str(generated_context.get("heuristic_primary", "")).strip() or old_label,
            "hybrid_live_source": str(generated_context.get("hybrid_live_source", "")).strip(),
            "review_status": review_status,
            "feedback_strength": "strong",
            "folder_match_source": str((folder_hint or {}).get("match_source", "")),
        }

    source_path = (
        metadata.get("canonical_source_path", "")
        or metadata.get("source_file", "")
        or note_path.as_posix()
    )
    if explicit_primary:
        correct_label = explicit_primary
        secondary_labels = explicit_secondary
        review_status = "manual-obsidian-note"
        feedback_strength = "strong"
    elif folder_hint:
        correct_label = str(folder_hint.get("primary_label", "")).strip()
        secondary_labels = [
            str(item).strip()
            for item in (folder_hint.get("secondary_labels", []) or [])
            if str(item).strip()
        ]
        review_status = "manual-folder-weak-label"
        feedback_strength = "weak"
    else:
        correct_label = "markdown-note"
        secondary_labels = []
        review_status = "manual-obsidian-note"
        feedback_strength = "strong"

    return {
        "state_key": note_path.as_posix(),
        "source_path": source_path,
        "filename": Path(source_path).name or note_path.name,
        "source_filename": note_path.name,
        "correct_label": correct_label,
        "old_label": metadata.get("old_label", "").strip() or "unknown",
        "secondary_labels": secondary_labels,
        "summary": summary,
        "note": f"manual-obsidian-note:{relative_path.as_posix()}",
        "parser": "obsidian-markdown",
        "review_status": review_status,
        "feedback_strength": feedback_strength,
        "folder_match_source": str((folder_hint or {}).get("match_source", "")),
    }


def _derive_generated_note_feedback_context(
    *,
    source_path_text: str,
    metadata: dict[str, str],
    known_labels: list[str],
) -> dict[str, str]:
    existing_parser = str(metadata.get("source_parser", "")).strip()
    existing_heuristic = str(metadata.get("heuristic_primary_hint", "")).strip()
    existing_live_source = str(metadata.get("hybrid_live_source", "")).strip()
    if existing_parser and existing_heuristic and existing_live_source:
        return {
            "parser": existing_parser,
            "heuristic_primary": existing_heuristic,
            "hybrid_live_source": existing_live_source,
        }

    source_path = Path(source_path_text)
    if not source_path.exists() or not source_path.is_file():
        return {
            "parser": existing_parser or "obsidian-generated-note",
            "heuristic_primary": existing_heuristic or "unknown",
            "hybrid_live_source": existing_live_source,
        }

    parser = existing_parser
    heuristic_primary = existing_heuristic
    hybrid_live_source = existing_live_source

    try:
        from apps.classifier.classify_to_obsidian import (
            IMAGE_EXTENSIONS,
            SPREADSHEET_EXTENSIONS,
            classify_document_fast,
            classify_spreadsheet_fast,
            parse_document,
        )
        from packages.classification.ocr_pipeline import extract_image_text_with_metadata

        ext = source_path.suffix.lower()
        if ext in SPREADSHEET_EXTENSIONS:
            markdown, heuristic_result, spreadsheet_metadata = classify_spreadsheet_fast(
                source_path=source_path,
                categories=known_labels,
            )
            parser = parser or str(spreadsheet_metadata.get("parser", "")).strip() or "spreadsheet-openpyxl"
            heuristic_primary = (
                heuristic_primary
                or str((heuristic_result or {}).get("primary_label", "")).strip()
                or "unknown"
            )
        elif ext in IMAGE_EXTENSIONS:
            ocr_evidence = extract_image_text_with_metadata(source_path)
            ocr_text = str(ocr_evidence.get("text", "") or "")
            ocr_engine = str(ocr_evidence.get("engine", "") or "").strip()
            parser = parser or (f"image-ocr-{ocr_engine}".rstrip("-") if ocr_text.strip() else "image-binary")
            heuristic_result = classify_document_fast(
                source_path=source_path,
                markdown=ocr_text,
                categories=known_labels,
            )
            heuristic_primary = (
                heuristic_primary
                or str((heuristic_result or {}).get("primary_label", "")).strip()
                or "unknown"
            )
        else:
            with TemporaryDirectory() as work_dir:
                markdown, parser_name, _ = parse_document(source_path, Path(work_dir))
            parser = parser or str(parser_name or "").strip() or "unknown"
            heuristic_result = classify_document_fast(
                source_path=source_path,
                markdown=markdown,
                categories=known_labels,
            )
            heuristic_primary = (
                heuristic_primary
                or str((heuristic_result or {}).get("primary_label", "")).strip()
                or "unknown"
            )
    except Exception:
        pass

    return {
        "parser": parser or "obsidian-generated-note",
        "heuristic_primary": heuristic_primary or "unknown",
        "hybrid_live_source": hybrid_live_source,
    }


def _manual_feedback_fingerprint(
    *,
    note_path: Path,
    feedback_entry: dict[str, object],
) -> str:
    return (
        f"{note_path.as_posix()}:"
        f"{note_path.stat().st_mtime_ns}:"
        f"{note_path.stat().st_size}:"
        f"{feedback_entry.get('correct_label', '')}:"
        f"{feedback_entry.get('review_status', '')}:"
        f"{feedback_entry.get('parser', '')}:"
        f"{feedback_entry.get('heuristic_primary', '')}:"
        f"{feedback_entry.get('hybrid_live_source', '')}"
    )


def _iter_manual_notes(vault_root: Path) -> list[tuple[Path, dict[str, str], str]]:
    notes: list[tuple[Path, dict[str, str], str]] = []
    for note_path in vault_root.rglob("*.md"):
        if note_path.name == "Classification Index.md":
            continue
        relative_parts = note_path.relative_to(vault_root).parts
        if relative_parts and relative_parts[0] in MANUAL_NOTE_SKIP_PREFIXES:
            continue
        note_text = note_path.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_frontmatter(note_text)
        metadata = parsed[0] if parsed is not None else {}
        notes.append((note_path.resolve(), metadata, note_text))
    notes.sort(key=lambda item: str(item[0]).lower())
    return notes


def repair_vault_source_links(
    vault_root: Path,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    result = {
        "scanned": 0,
        "repaired": 0,
        "skipped": 0,
    }
    note_limit = limit if limit is not None else 0
    notes = _iter_generated_notes(vault_root)
    if note_limit > 0:
        notes = notes[:note_limit]

    for note_path, metadata in notes:
        result["scanned"] += 1
        note_text = note_path.read_text(encoding="utf-8", errors="replace")
        repaired_note_text, changed = _repair_note_links(note_text, metadata)
        if not changed:
            result["skipped"] += 1
            continue
        note_path.write_text(repaired_note_text, encoding="utf-8")
        result["repaired"] += 1
    return result


def sync_manual_note_feedback(
    vault_root: Path,
    *,
    feedback_path: Path,
    state_path: Path,
    known_labels: list[str] | None = None,
    folder_label_map_path: Path | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    result = {
        "scanned": 0,
        "exported": 0,
        "unchanged": 0,
    }
    existing_state: dict[str, str] = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing_state = {str(key): str(value) for key, value in loaded.items()}
        except json.JSONDecodeError:
            existing_state = {}

    note_limit = limit if limit is not None else 0
    notes = _iter_manual_notes(vault_root)
    if note_limit > 0:
        notes = notes[:note_limit]

    known_label_aliases = _build_known_label_aliases(known_labels or [])
    folder_label_map = _load_vault_folder_label_map(folder_label_map_path)
    updated_state = dict(existing_state)
    feedback_rows: list[dict[str, object]] = []
    for note_path, metadata, note_text in notes:
        result["scanned"] += 1
        feedback_entry = _manual_feedback_entry(
            vault_root=vault_root,
            note_path=note_path,
            metadata=metadata,
            note_text=note_text,
            known_labels=known_labels or [],
            known_label_aliases=known_label_aliases,
            folder_label_map=folder_label_map,
        )
        if feedback_entry is None:
            result["unchanged"] += 1
            continue

        state_key = str(feedback_entry.pop("state_key"))
        fingerprint = _manual_feedback_fingerprint(
            note_path=note_path,
            feedback_entry=feedback_entry,
        )
        if existing_state.get(state_key) == fingerprint:
            result["unchanged"] += 1
            continue

        feedback_rows.append(
            {
                "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                **feedback_entry,
            }
        )
        updated_state[state_key] = fingerprint
        result["exported"] += 1

    if feedback_rows:
        feedback_path.parent.mkdir(parents=True, exist_ok=True)
        with feedback_path.open("a", encoding="utf-8") as handle:
            for row in feedback_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(updated_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def collect_targeted_manual_feedback(
    vault_root: Path,
    *,
    known_labels: list[str] | None = None,
    folder_label_map_path: Path | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    note_limit = limit if limit is not None else 0
    notes = _iter_manual_notes(vault_root)
    if note_limit > 0:
        notes = notes[:note_limit]

    known_label_aliases = _build_known_label_aliases(known_labels or [])
    folder_label_map = _load_vault_folder_label_map(folder_label_map_path)
    rows: list[dict[str, object]] = []

    for note_path, metadata, note_text in notes:
        feedback_entry = _manual_feedback_entry(
            vault_root=vault_root,
            note_path=note_path,
            metadata=metadata,
            note_text=note_text,
            known_labels=known_labels or [],
            known_label_aliases=known_label_aliases,
            folder_label_map=folder_label_map,
        )
        if feedback_entry is None:
            continue
        if str(feedback_entry.get("feedback_strength", "")).strip().lower() != "strong":
            continue

        source_path = str(feedback_entry.get("source_path", "")).strip()
        correct_label = str(feedback_entry.get("correct_label", "")).strip()
        old_label = str(feedback_entry.get("old_label", "")).strip()
        if not source_path or not correct_label:
            continue
        if old_label and old_label == correct_label:
            continue

        rows.append(
            {
                **feedback_entry,
                "note_path": str(note_path),
                "note_modified_at": datetime.fromtimestamp(
                    note_path.stat().st_mtime,
                    tz=timezone.utc,
                ),
            }
        )

    rows.sort(
        key=lambda item: (
            cast(datetime, item["note_modified_at"]),
            str(item.get("note_path", "")).lower(),
        ),
        reverse=True,
    )
    return rows


def _find_matching_generated_notes(
    vault_root: Path,
    *,
    canonical_source_path: str,
    canonical_source_hash: str,
    last_seen_filename: str,
) -> list[tuple[int, Path, dict[str, str]]]:
    matches: list[tuple[int, Path, dict[str, str]]] = []
    for note_path, metadata in _iter_generated_notes(vault_root):
        rank: int | None = None
        if canonical_source_path and metadata.get("canonical_source_path") == canonical_source_path:
            rank = 0
        elif canonical_source_hash and metadata.get("canonical_source_hash") == canonical_source_hash:
            rank = 1
        elif last_seen_filename and metadata.get("last_seen_filename") == last_seen_filename:
            rank = 2
        if rank is not None:
            matches.append((rank, note_path, metadata))
    matches.sort(key=lambda item: (item[0], _note_suffix_rank(item[1].name), str(item[1]).lower()))
    return matches


def _parse_json_object(raw_value: str | None) -> dict[str, object]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _update_state_note_references(
    state: ClassificationState,
    *,
    note_reference: str,
    note_metadata: dict[str, str],
) -> bool:
    changed = False
    if state.classifier_note_path != note_reference:
        state.classifier_note_path = note_reference
        changed = True

    manifest_record = _parse_json_object(state.classifier_manifest_record)
    if manifest_record:
        if manifest_record.get("note_path") != note_reference:
            manifest_record["note_path"] = note_reference
            changed = True
        canonical_source_path = note_metadata.get("canonical_source_path", "")
        if canonical_source_path and manifest_record.get("canonical_source_path") != canonical_source_path:
            manifest_record["canonical_source_path"] = canonical_source_path
            changed = True
        canonical_source_hash = note_metadata.get("canonical_source_hash", "")
        if canonical_source_hash and manifest_record.get("canonical_source_hash") != canonical_source_hash:
            manifest_record["canonical_source_hash"] = canonical_source_hash
            changed = True
        last_seen_filename = note_metadata.get("last_seen_filename", "")
        if last_seen_filename and manifest_record.get("last_seen_filename") != last_seen_filename:
            manifest_record["last_seen_filename"] = last_seen_filename
            changed = True
        for field in ("attachment_mode", "compatibility_attachment_path", "source_link"):
            field_value = note_metadata.get(field, "")
            if manifest_record.get(field) != field_value:
                manifest_record[field] = field_value
                changed = True
        if changed:
            state.classifier_manifest_record = json.dumps(manifest_record, ensure_ascii=False)

    response_payload = _parse_json_object(state.response_payload_json)
    if response_payload:
        response_changed = False
        record_payload = response_payload.get("record")
        if isinstance(record_payload, dict):
            if record_payload.get("note_path") != note_reference:
                record_payload["note_path"] = note_reference
                response_changed = True
            canonical_source_path = note_metadata.get("canonical_source_path", "")
            if canonical_source_path and record_payload.get("canonical_source_path") != canonical_source_path:
                record_payload["canonical_source_path"] = canonical_source_path
                response_changed = True
            canonical_source_hash = note_metadata.get("canonical_source_hash", "")
            if canonical_source_hash and record_payload.get("canonical_source_hash") != canonical_source_hash:
                record_payload["canonical_source_hash"] = canonical_source_hash
                response_changed = True
            last_seen_filename = note_metadata.get("last_seen_filename", "")
            if last_seen_filename and record_payload.get("last_seen_filename") != last_seen_filename:
                record_payload["last_seen_filename"] = last_seen_filename
                response_changed = True
            for field in ("attachment_mode", "compatibility_attachment_path", "source_link"):
                field_value = note_metadata.get(field, "")
                if record_payload.get(field) != field_value:
                    record_payload[field] = field_value
                    response_changed = True
        if response_changed:
            state.response_payload_json = json.dumps(response_payload, ensure_ascii=False)
            changed = True

    return changed


def _select_replacement_candidate(
    *,
    session: Session,
    mirror_root: Path,
    canonical_source_hash: str,
    last_seen_filename: str,
) -> tuple[str, Path | None]:
    candidates = _iter_live_candidates(session, mirror_root)

    hash_matches = []
    exact_name_matches = []
    close_name_matches = []
    normalized_last_seen = _normalize_name(last_seen_filename) if last_seen_filename else ""

    for file_record, candidate_path in candidates:
        if canonical_source_hash and _sha256_file(candidate_path) == canonical_source_hash:
            hash_matches.append(candidate_path)

        if last_seen_filename and file_record.name == last_seen_filename:
            exact_name_matches.append(candidate_path)

        if normalized_last_seen and _normalize_name(file_record.name) == normalized_last_seen:
            close_name_matches.append(candidate_path)

    if canonical_source_hash:
        if len(hash_matches) == 1:
            return "repair", hash_matches[0]
        if len(hash_matches) > 1:
            return "ambiguous", None

    if last_seen_filename:
        if len(exact_name_matches) == 1:
            return "repair", exact_name_matches[0]
        if len(exact_name_matches) > 1:
            return "ambiguous", None
        if len(close_name_matches) == 1:
            return "repair", close_name_matches[0]
        if len(close_name_matches) > 1:
            return "ambiguous", None

    return "unverified", None


def run_vault_reconciliation_once(
    session: Session,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    result = {
        "scanned": 0,
        "repaired": 0,
        "ambiguous": 0,
        "unverified": 0,
        "skipped": 0,
    }
    if not get_vault_reconciliation_enabled():
        return result

    mirror_root = _resolve_mirror_root()
    vault_root = _resolve_vault_root()
    if mirror_root is None or vault_root is None:
        return result

    active_limit = limit if limit is not None else get_vault_reconciliation_limit()
    states = session.scalars(
        select(ClassificationState)
        .where(ClassificationState.submission_status == "completed")
        .where(ClassificationState.classifier_note_path.is_not(None))
        .order_by(ClassificationState.id.asc())
        .limit(active_limit)
    ).all()
    database_changed = False

    for state in states:
        result["scanned"] += 1
        state_repaired = False
        note_path_value = state.classifier_note_path or ""
        note_path = _resolve_note_path(note_path_value, vault_root) if note_path_value else None
        note_text = ""
        metadata: dict[str, str] = {}
        if note_path_value and note_path is not None and note_path.exists() and note_path.is_file():
            note_text = note_path.read_text(encoding="utf-8", errors="replace")
            parsed = _parse_frontmatter(note_text)
            if parsed is not None:
                metadata, _, _ = parsed

        manifest_record = _parse_json_object(state.classifier_manifest_record)
        state_metadata = _build_state_note_metadata(
            state,
            manifest_record=manifest_record,
        )
        file_record = session.get(FileRecord, state.file_id)
        fallback_source_path = ""
        fallback_last_seen_filename = ""
        if file_record is not None:
            fallback_last_seen_filename = file_record.name
            if mirror_root is not None:
                fallback_source_path = str(
                    (mirror_root / file_record.path.lstrip("/")).resolve()
                )

        canonical_source_path = (
            metadata.get("canonical_source_path", "")
            or str(manifest_record.get("canonical_source_path") or "")
            or fallback_source_path
        )
        canonical_source_hash = (
            metadata.get("canonical_source_hash", "")
            or str(manifest_record.get("canonical_source_hash") or "")
        )
        last_seen_filename = (
            metadata.get("last_seen_filename", "")
            or str(manifest_record.get("last_seen_filename") or "")
            or fallback_last_seen_filename
        )
        if not canonical_source_path or not last_seen_filename:
            result["unverified"] += 1
            continue

        matching_notes = _find_matching_generated_notes(
            vault_root,
            canonical_source_path=canonical_source_path,
            canonical_source_hash=canonical_source_hash,
            last_seen_filename=last_seen_filename,
        )
        preferred_note_path: Path | None = None
        preferred_metadata: dict[str, str] = metadata
        if matching_notes:
            _, preferred_note_path, preferred_metadata = matching_notes[0]
            preferred_reference = _vault_note_reference(preferred_note_path, vault_root)
            if _update_state_note_references(
                state,
                note_reference=preferred_reference,
                note_metadata=preferred_metadata,
            ):
                database_changed = True
                state_repaired = True

        active_note_path = preferred_note_path or note_path
        active_metadata = preferred_metadata if preferred_note_path is not None else metadata
        active_metadata = _merge_note_metadata(
            active_metadata,
            state_metadata=state_metadata,
        )
        if active_note_path is None or not active_note_path.exists() or not active_note_path.is_file():
            result["skipped"] += 1
            continue

        active_note_text = active_note_path.read_text(encoding="utf-8", errors="replace")
        repaired_note_text, note_link_changed = _repair_note_links(active_note_text, active_metadata)
        if note_link_changed:
            active_note_path.write_text(repaired_note_text, encoding="utf-8")
            state_repaired = True
            database_changed = True
            parsed = _parse_frontmatter(repaired_note_text)
            if parsed is not None:
                active_metadata, _, _ = parsed
                note_reference = _vault_note_reference(active_note_path, vault_root)
                if _update_state_note_references(
                    state,
                    note_reference=note_reference,
                    note_metadata=active_metadata,
                ):
                    database_changed = True

        current_source_path = Path(
            active_metadata.get("canonical_source_path", canonical_source_path)
        )
        if current_source_path.exists():
            if state_repaired:
                result["repaired"] += 1
            continue

        decision, replacement_path = _select_replacement_candidate(
            session=session,
            mirror_root=mirror_root,
            canonical_source_hash=canonical_source_hash,
            last_seen_filename=last_seen_filename,
        )
        if decision == "ambiguous":
            if state_repaired:
                result["repaired"] += 1
            result["ambiguous"] += 1
            continue
        if decision != "repair" or replacement_path is None:
            if state_repaired:
                result["repaired"] += 1
            result["unverified"] += 1
            continue

        updated_note = _update_frontmatter_fields(
            active_note_path.read_text(encoding="utf-8", errors="replace"),
            {
                "canonical_source_path": str(replacement_path),
                "canonical_source_hash": active_metadata.get("canonical_source_hash", "") or canonical_source_hash or _sha256_file(replacement_path),
                "last_seen_filename": replacement_path.name,
                "attachment_mode": active_metadata.get("attachment_mode", "none"),
                "compatibility_attachment_path": active_metadata.get("compatibility_attachment_path", ""),
                "source_link": active_metadata.get("source_link", ""),
                "attachment": active_metadata.get("attachment", ""),
            },
        )
        refreshed_metadata = dict(active_metadata)
        refreshed_metadata["canonical_source_path"] = str(replacement_path)
        refreshed_metadata["canonical_source_hash"] = (
            active_metadata.get("canonical_source_hash", "") or canonical_source_hash or _sha256_file(replacement_path)
        )
        refreshed_metadata["last_seen_filename"] = replacement_path.name
        refreshed_note_text, _ = _repair_note_links(updated_note, refreshed_metadata)
        active_note_path.write_text(refreshed_note_text, encoding="utf-8")
        state_repaired = True
        database_changed = True
        parsed = _parse_frontmatter(refreshed_note_text)
        if parsed is not None:
            refreshed_metadata, _, _ = parsed
        note_reference = _vault_note_reference(active_note_path, vault_root)
        _update_state_note_references(
            state,
            note_reference=note_reference,
            note_metadata=refreshed_metadata,
        )
        if state_repaired:
            result["repaired"] += 1

    if database_changed:
        session.commit()
    return result
