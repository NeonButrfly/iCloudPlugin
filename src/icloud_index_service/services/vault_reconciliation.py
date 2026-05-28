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
    for root_name in ("01 Classified", "02 Needs Review"):
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
                result["repaired"] += 1

        active_note_path = preferred_note_path or note_path
        active_metadata = preferred_metadata if preferred_note_path is not None else metadata
        if active_note_path is None or not active_note_path.exists() or not active_note_path.is_file():
            result["skipped"] += 1
            continue

        current_source_path = Path(
            active_metadata.get("canonical_source_path", canonical_source_path)
        )
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
            active_note_path.read_text(encoding="utf-8", errors="replace"),
            {
                "canonical_source_path": str(replacement_path),
                "canonical_source_hash": active_metadata.get("canonical_source_hash", "") or canonical_source_hash or _sha256_file(replacement_path),
                "last_seen_filename": replacement_path.name,
                "attachment_mode": active_metadata.get("attachment_mode", "none"),
                "compatibility_attachment_path": active_metadata.get("compatibility_attachment_path", ""),
            },
        )
        active_note_path.write_text(updated_note, encoding="utf-8")
        result["repaired"] += 1
        database_changed = True
        refreshed_metadata = dict(active_metadata)
        refreshed_metadata["canonical_source_path"] = str(replacement_path)
        refreshed_metadata["canonical_source_hash"] = (
            active_metadata.get("canonical_source_hash", "") or canonical_source_hash or _sha256_file(replacement_path)
        )
        refreshed_metadata["last_seen_filename"] = replacement_path.name
        note_reference = _vault_note_reference(active_note_path, vault_root)
        _update_state_note_references(
            state,
            note_reference=note_reference,
            note_metadata=refreshed_metadata,
        )

    if database_changed:
        session.commit()
    return result
