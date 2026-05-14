from __future__ import annotations

import os
from io import BytesIO


def extract_text_from_image_bytes(
    *,
    path: str,
    mime_type: str,
    payload: bytes,
) -> str:
    try:
        from PIL import Image, ImageOps
        import pytesseract
    except Exception:
        return ""

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass

    try:
        with Image.open(BytesIO(payload)) as image:
            normalized_image = ImageOps.exif_transpose(image).convert("RGB")
            text = pytesseract.image_to_string(
                normalized_image,
                lang=os.getenv("ICLOUD_OCR_LANGS", "eng"),
            )
    except Exception:
        return ""

    return text.strip()
