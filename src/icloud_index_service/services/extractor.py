from __future__ import annotations

from pathlib import PurePosixPath

from icloud_index_service.parsers.docx_parser import extract_text_from_docx_bytes
from icloud_index_service.parsers.pdf_parser import extract_text_from_pdf_bytes
from icloud_index_service.parsers.text_parser import extract_text_from_plaintext_bytes
from icloud_index_service.parsers.xlsx_parser import extract_text_from_xlsx_bytes


TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".log"}
DOCX_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}
XLSX_EXTENSIONS = {".xlsx"}


def summarize_text(text: str, limit: int) -> str:
    return text[:limit]


def extract_text_content(
    *,
    path: str,
    mime_type: str,
    payload: bytes,
) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    normalized_mime_type = mime_type.lower()

    if normalized_mime_type.startswith("text/") or suffix in TEXT_EXTENSIONS:
        return extract_text_from_plaintext_bytes(payload)
    if suffix in PDF_EXTENSIONS or normalized_mime_type == "application/pdf":
        return extract_text_from_pdf_bytes(payload)
    if (
        suffix in DOCX_EXTENSIONS
        or normalized_mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return extract_text_from_docx_bytes(payload)
    if (
        suffix in XLSX_EXTENSIONS
        or normalized_mime_type
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ):
        return extract_text_from_xlsx_bytes(payload)
    return ""
