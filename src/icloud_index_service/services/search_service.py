from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.extractor import summarize_text

LIKE_ESCAPE_CHAR = "\\"
MAX_FILE_CONTENT_CHARS = 10_000
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{1,63}")


def _path_contains_hidden_internal_segment(path_value: str) -> bool:
    normalized_path = str(path_value or "").replace("\\", "/").strip("/")
    if not normalized_path:
        return False
    return any(part.startswith("_") for part in normalized_path.split("/"))


def _load_retrieval_terms(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    try:
        loaded = json.loads(raw_value)
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for item in loaded:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(cleaned)
    return terms


def _score_text_matches(
    query_lower: str,
    query_tokens: list[str],
    value: str,
    *,
    full_weight: int,
    token_weight: int,
) -> int:
    lowered = str(value or "").lower()
    if not lowered:
        return 0
    score = full_weight if query_lower in lowered else 0
    score += sum(token_weight for token in query_tokens if token in lowered)
    return score


def _compute_match_score(
    *,
    query_lower: str,
    query_tokens: list[str],
    file_record: FileRecord,
    extracted_content: ExtractedContent | None,
    state: ClassificationState | None,
) -> int:
    retrieval_terms = _load_retrieval_terms(state.retrieval_terms_json if state is not None else None)
    score = 0
    score += _score_text_matches(query_lower, query_tokens, file_record.name, full_weight=180, token_weight=25)
    score += _score_text_matches(query_lower, query_tokens, file_record.path, full_weight=120, token_weight=18)
    score += _score_text_matches(query_lower, query_tokens, state.primary_label if state is not None else "", full_weight=220, token_weight=60)
    score += _score_text_matches(query_lower, query_tokens, state.summary if state is not None else "", full_weight=90, token_weight=18)
    score += _score_text_matches(query_lower, query_tokens, state.entity_summary if state is not None else "", full_weight=150, token_weight=30)
    score += _score_text_matches(query_lower, query_tokens, state.topic_summary if state is not None else "", full_weight=135, token_weight=28)
    score += _score_text_matches(query_lower, query_tokens, state.retrieval_text if state is not None else "", full_weight=110, token_weight=20)
    score += _score_text_matches(
        query_lower,
        query_tokens,
        extracted_content.content_text if extracted_content is not None else "",
        full_weight=70,
        token_weight=14,
    )
    score += sum(
        24
        for term in retrieval_terms
        if query_lower in term.lower() or any(token in term.lower() for token in query_tokens)
    )
    return score


def _build_match_reasons(
    *,
    query_lower: str,
    query_tokens: list[str],
    file_record: FileRecord,
    extracted_content: ExtractedContent | None,
    state: ClassificationState | None,
) -> list[str]:
    reasons: list[str] = []
    fields = {
        "name": file_record.name,
        "path": file_record.path,
        "label": state.primary_label if state is not None else "",
        "summary": state.summary if state is not None else "",
        "entities": state.entity_summary if state is not None else "",
        "topics": state.topic_summary if state is not None else "",
        "content": extracted_content.content_text if extracted_content is not None else "",
    }
    for label, value in fields.items():
        lowered = str(value or "").lower()
        if not lowered:
            continue
        if query_lower in lowered or any(token in lowered for token in query_tokens):
            reasons.append(label)
    return reasons[:4]


def _serialize_file_match(
    file_record: FileRecord,
    extracted_content: ExtractedContent | None,
    state: ClassificationState | None,
    *,
    match_reasons: list[str],
) -> dict[str, Any]:
    content_text = extracted_content.content_text if extracted_content is not None else ""
    retrieval_terms = _load_retrieval_terms(state.retrieval_terms_json if state is not None else None)
    return {
        "file_id": file_record.id,
        "external_id": file_record.external_id,
        "name": file_record.name,
        "path": file_record.path,
        "mime_type": file_record.mime_type,
        "excerpt": summarize_text(content_text, 280),
        "primary_label": state.primary_label if state is not None else None,
        "summary": state.summary if state is not None else None,
        "confidence": state.confidence if state is not None else None,
        "entity_summary": state.entity_summary if state is not None else None,
        "topic_summary": state.topic_summary if state is not None else None,
        "retrieval_terms": retrieval_terms,
        "classifier_note_path": state.classifier_note_path if state is not None else None,
        "match_reasons": match_reasons,
    }


def build_database_unavailable_detail(
    *,
    operation: str,
    startup_validation_error: str | None = None,
) -> dict[str, str]:
    payload = {
        "status": "degraded",
        "database": "unavailable",
        "operation": operation,
    }
    if startup_validation_error is not None:
        payload["startup_validation_error"] = startup_validation_error
    return payload


def build_auth_needed_response(*, has_cached_results: bool) -> dict[str, object]:
    return {
        "auth_status": "needs-bootstrap",
        "has_cached_results": has_cached_results,
    }


def _escape_like_fragment(value: str) -> str:
    return (
        value.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
        .replace("%", f"{LIKE_ESCAPE_CHAR}%")
        .replace("_", f"{LIKE_ESCAPE_CHAR}_")
    )


def _normalize_path_scope(path_scope: str) -> str:
    trimmed_path_scope = path_scope.strip()
    if not trimmed_path_scope or trimmed_path_scope == "/":
        return "/"
    normalized_path_scope = trimmed_path_scope.rstrip("/")
    if not normalized_path_scope.startswith("/"):
        normalized_path_scope = f"/{normalized_path_scope}"
    return f"{normalized_path_scope}/"


def search_files(
    session: Session,
    *,
    query: str,
    limit: int,
    path_scope: str | None = None,
) -> list[dict[str, Any]]:
    normalized_query = query.strip()
    if not normalized_query:
        return []

    pattern = f"%{_escape_like_fragment(normalized_query)}%"
    query_lower = normalized_query.lower()
    query_tokens = [token.lower() for token in TOKEN_RE.findall(normalized_query)]
    statement = (
        select(FileRecord, ExtractedContent, ClassificationState)
        .outerjoin(ExtractedContent, ExtractedContent.file_id == FileRecord.id)
        .outerjoin(ClassificationState, ClassificationState.file_id == FileRecord.id)
        .where(FileRecord.is_deleted.is_(False))
        .where(
            or_(
                FileRecord.name.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                FileRecord.path.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ExtractedContent.content_text.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ClassificationState.primary_label.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ClassificationState.summary.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ClassificationState.entity_summary.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ClassificationState.topic_summary.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ClassificationState.retrieval_text.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ClassificationState.retrieval_terms_json.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
            )
        )
    )
    if path_scope:
        normalized_path_scope = _normalize_path_scope(path_scope)
        path_pattern = f"{_escape_like_fragment(normalized_path_scope)}%"
        statement = statement.where(
            FileRecord.path.ilike(path_pattern, escape=LIKE_ESCAPE_CHAR)
        )

    candidates = session.execute(
        statement.order_by(FileRecord.id.asc()).limit(max(limit * 8, 40))
    ).all()
    candidates = [
        row
        for row in candidates
        if not _path_contains_hidden_internal_segment(row[0].path)
    ]
    ranked = sorted(
        candidates,
        key=lambda row: (
            -_compute_match_score(
                query_lower=query_lower,
                query_tokens=query_tokens,
                file_record=row[0],
                extracted_content=row[1],
                state=row[2],
            ),
            row[0].id,
        ),
    )
    return [
        _serialize_file_match(
            file_record,
            extracted_content,
            state,
            match_reasons=_build_match_reasons(
                query_lower=query_lower,
                query_tokens=query_tokens,
                file_record=file_record,
                extracted_content=extracted_content,
                state=state,
            ),
        )
        for file_record, extracted_content, state in ranked[:limit]
    ]


def get_file_details(session: Session, *, file_id: int) -> dict[str, Any] | None:
    capped_content = func.substr(
        ExtractedContent.content_text,
        1,
        MAX_FILE_CONTENT_CHARS,
    )
    content_length = func.length(ExtractedContent.content_text)
    statement = (
        select(
            FileRecord,
            capped_content,
            content_length,
            ClassificationState,
        )
        .outerjoin(ExtractedContent, ExtractedContent.file_id == FileRecord.id)
        .outerjoin(ClassificationState, ClassificationState.file_id == FileRecord.id)
        .where(FileRecord.id == file_id)
        .where(FileRecord.is_deleted.is_(False))
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        return None

    file_record, capped_content_text, extracted_content_length, state = row
    if _path_contains_hidden_internal_segment(file_record.path):
        return None
    content_text = capped_content_text or ""
    content_length_value = (
        int(extracted_content_length) if extracted_content_length is not None else 0
    )
    retrieval_terms = _load_retrieval_terms(state.retrieval_terms_json if state is not None else None)
    return {
        "file_id": file_record.id,
        "external_id": file_record.external_id,
        "name": file_record.name,
        "path": file_record.path,
        "mime_type": file_record.mime_type,
        "excerpt": summarize_text(content_text, 280),
        "content_text": content_text,
        "content_length": content_length_value,
        "content_truncated": content_length_value > MAX_FILE_CONTENT_CHARS,
        "primary_label": state.primary_label if state is not None else None,
        "summary": state.summary if state is not None else None,
        "confidence": state.confidence if state is not None else None,
        "entity_summary": state.entity_summary if state is not None else None,
        "topic_summary": state.topic_summary if state is not None else None,
        "retrieval_terms": retrieval_terms,
        "classifier_note_path": state.classifier_note_path if state is not None else None,
    }
