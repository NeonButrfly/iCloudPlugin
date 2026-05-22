from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord

DEFAULT_VAULT_RECONCILIATION_LIMIT = 10
OWNED_FRONTMATTER_FIELDS = (
    "canonical_source_path",
    "canonical_source_hash",
    "last_seen_filename",
    "attachment_mode",
    "compatibility_attachment_path",
)


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


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


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

    for state in states:
        result["scanned"] += 1
        note_path_value = state.classifier_note_path or ""
        if not note_path_value:
            result["skipped"] += 1
            continue

        note_path = _resolve_note_path(note_path_value, vault_root)
        if not note_path.exists() or not note_path.is_file():
            result["skipped"] += 1
            continue

        note_text = note_path.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_frontmatter(note_text)
        if parsed is None:
            result["skipped"] += 1
            continue

        metadata, _, _ = parsed
        canonical_source_path = metadata.get("canonical_source_path", "")
        canonical_source_hash = metadata.get("canonical_source_hash", "")
        last_seen_filename = metadata.get("last_seen_filename", "")
        if not canonical_source_path or not last_seen_filename:
            result["unverified"] += 1
            continue

        current_source_path = Path(canonical_source_path)
        if current_source_path.exists():
            continue

        decision, replacement_path = _select_replacement_candidate(
            session=session,
            mirror_root=mirror_root,
            canonical_source_hash=canonical_source_hash,
            last_seen_filename=last_seen_filename,
        )
        if decision == "ambiguous":
            result["ambiguous"] += 1
            continue
        if decision != "repair" or replacement_path is None:
            result["unverified"] += 1
            continue

        updated_note = _update_frontmatter_fields(
            note_text,
            {
                "canonical_source_path": str(replacement_path),
                "canonical_source_hash": canonical_source_hash or _sha256_file(replacement_path),
                "last_seen_filename": replacement_path.name,
                "attachment_mode": metadata.get("attachment_mode", "none"),
                "compatibility_attachment_path": metadata.get("compatibility_attachment_path", ""),
            },
        )
        note_path.write_text(updated_note, encoding="utf-8")
        result["repaired"] += 1

    return result
