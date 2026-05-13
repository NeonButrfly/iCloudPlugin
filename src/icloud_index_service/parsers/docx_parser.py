from __future__ import annotations

from io import BytesIO


def extract_text_from_docx_bytes(payload: bytes) -> str:
    from docx import Document

    document = Document(BytesIO(payload))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text).strip()
