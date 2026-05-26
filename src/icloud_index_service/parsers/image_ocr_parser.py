from __future__ import annotations

from packages.classification.ocr_pipeline import extract_image_text_with_metadata


def extract_text_from_image_bytes(
    *,
    path: str,
    mime_type: str,
    payload: bytes,
) -> str:
    return str(
        extract_image_text_with_metadata(
            path=path,
            mime_type=mime_type,
            payload=payload,
        ).get("text", "")
    ).strip()
