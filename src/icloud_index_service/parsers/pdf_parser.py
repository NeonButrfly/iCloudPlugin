from __future__ import annotations

from io import BytesIO


def extract_text_from_pdf_bytes(payload: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
