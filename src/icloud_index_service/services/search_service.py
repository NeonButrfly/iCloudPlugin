from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.extractor import summarize_text

LIKE_ESCAPE_CHAR = "\\"


def _serialize_file_match(
    file_record: FileRecord,
    extracted_content: ExtractedContent | None,
) -> dict[str, Any]:
    content_text = extracted_content.content_text if extracted_content is not None else ""
    return {
        "file_id": file_record.id,
        "external_id": file_record.external_id,
        "name": file_record.name,
        "path": file_record.path,
        "mime_type": file_record.mime_type,
        "excerpt": summarize_text(content_text, 280),
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


def _escape_like_fragment(value: str) -> str:
    return (
        value.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
        .replace("%", f"{LIKE_ESCAPE_CHAR}%")
        .replace("_", f"{LIKE_ESCAPE_CHAR}_")
    )


def search_files(session: Session, *, query: str, limit: int) -> list[dict[str, Any]]:
    normalized_query = query.strip()
    if not normalized_query:
        return []

    pattern = f"%{_escape_like_fragment(normalized_query)}%"
    statement = (
        select(FileRecord, ExtractedContent)
        .outerjoin(ExtractedContent, ExtractedContent.file_id == FileRecord.id)
        .where(FileRecord.is_deleted.is_(False))
        .where(
            or_(
                FileRecord.name.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                FileRecord.path.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                ExtractedContent.content_text.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
            )
        )
        .order_by(FileRecord.id.asc())
        .limit(limit)
    )

    return [
        _serialize_file_match(file_record, extracted_content)
        for file_record, extracted_content in session.execute(statement).all()
    ]


def get_file_details(session: Session, *, file_id: int) -> dict[str, Any] | None:
    statement = (
        select(FileRecord, ExtractedContent)
        .outerjoin(ExtractedContent, ExtractedContent.file_id == FileRecord.id)
        .where(FileRecord.id == file_id)
        .where(FileRecord.is_deleted.is_(False))
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        return None

    file_record, extracted_content = row
    content_text = extracted_content.content_text if extracted_content is not None else ""
    return {
        **_serialize_file_match(file_record, extracted_content),
        "content_text": content_text,
    }
