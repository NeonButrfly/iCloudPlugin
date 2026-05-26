from __future__ import annotations

from packages.classification.ocr_pipeline import extract_pdf_text_with_metadata


def extract_text_from_pdf_bytes(payload: bytes) -> str:
    return str(extract_pdf_text_with_metadata(payload).get("text", "")).strip()
