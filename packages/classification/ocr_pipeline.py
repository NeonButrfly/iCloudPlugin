from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").replace("\x00", " ").split()).strip()


def _char_count(text: str) -> int:
    return sum(1 for char in text if char.isalnum())


def _quality_for_text(text: str) -> str:
    chars = _char_count(text)
    if chars >= 120:
        return "high"
    if chars >= 20:
        return "medium"
    if chars >= 8:
        return "low"
    return "empty"


def _ocr_languages() -> str:
    return os.getenv("ICLOUD_OCR_LANGS", "eng").strip() or "eng"


def _paddle_enabled() -> bool:
    return os.getenv("ICLOUD_PADDLE_OCR_ENABLED", "1").strip().lower() not in {"", "0", "false", "no", "off"}


def _pdf_native_text_min_chars() -> int:
    try:
        return int(os.getenv("ICLOUD_PDF_NATIVE_TEXT_MIN_CHARS", "80"))
    except ValueError:
        return 80


def _pdf_ocr_max_pages() -> int:
    try:
        return max(int(os.getenv("ICLOUD_PDF_OCR_MAX_PAGES", "6")), 1)
    except ValueError:
        return 6


def _pdf_ocr_dpi() -> int:
    try:
        return max(int(os.getenv("ICLOUD_PDF_OCR_DPI", "200")), 72)
    except ValueError:
        return 200


def _flatten_paddle_result(node: Any, out: list[str]) -> None:
    if isinstance(node, str):
        if node.strip():
            out.append(node.strip())
        return
    if isinstance(node, dict):
        for value in node.values():
            _flatten_paddle_result(value, out)
        return
    if isinstance(node, (list, tuple)):
        if len(node) >= 2 and isinstance(node[1], (list, tuple)) and node[1]:
            first = node[1][0]
            if isinstance(first, str) and first.strip():
                out.append(first.strip())
                return
        for item in node:
            _flatten_paddle_result(item, out)


@lru_cache(maxsize=1)
def _load_paddleocr_engine():
    if not _paddle_enabled():
        return None
    try:
        from paddleocr import PaddleOCR
    except Exception:
        return None

    try:
        return PaddleOCR(use_angle_cls=True, lang=_ocr_languages())
    except Exception:
        return None


def _extract_image_text_with_paddleocr(*, path: str, mime_type: str, payload: bytes) -> str:
    engine = _load_paddleocr_engine()
    if engine is None:
        return ""

    def run_ocr(target: str) -> str:
        try:
            result = engine.ocr(target, cls=True)
        except TypeError:
            result = engine.ocr(target)
        except Exception:
            try:
                result = engine.predict(target)
            except Exception:
                return ""

        parts: list[str] = []
        _flatten_paddle_result(result, parts)
        return _normalize_text(" ".join(parts))

    source_path = Path(path) if path else None
    if source_path and source_path.exists():
        return run_ocr(str(source_path))

    suffix = Path(path or "image.png").suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    try:
        return run_ocr(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)


def _extract_image_text_with_tesseract(*, path: str, mime_type: str, payload: bytes) -> str:
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
            normalized = ImageOps.exif_transpose(image).convert("L")
            normalized = ImageOps.autocontrast(normalized)
            binary = normalized.point(lambda value: 255 if value > 180 else 0)
            psm6 = pytesseract.image_to_string(binary, lang=_ocr_languages(), config="--psm 6")
            psm11 = pytesseract.image_to_string(binary, lang=_ocr_languages(), config="--psm 11")
    except Exception:
        return ""

    candidates = [_normalize_text(psm6), _normalize_text(psm11)]
    return max(candidates, key=_char_count, default="")


def extract_image_text_with_metadata(*, path: str, mime_type: str, payload: bytes) -> dict[str, Any]:
    paddle_text = _normalize_text(
        _extract_image_text_with_paddleocr(path=path, mime_type=mime_type, payload=payload)
    )
    if paddle_text:
        return {
            "text": paddle_text,
            "engine": "paddleocr",
            "quality": _quality_for_text(paddle_text),
            "char_count": _char_count(paddle_text),
        }

    tesseract_text = _normalize_text(
        _extract_image_text_with_tesseract(path=path, mime_type=mime_type, payload=payload)
    )
    return {
        "text": tesseract_text,
        "engine": "tesseract" if tesseract_text else "",
        "quality": _quality_for_text(tesseract_text),
        "char_count": _char_count(tesseract_text),
    }


def _extract_native_pdf_text(payload: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(payload))
    return _normalize_text("\n".join(page.extract_text() or "" for page in reader.pages))


def _extract_pdf_text_via_page_ocr(payload: bytes, source_name: str = "") -> dict[str, Any]:
    if shutil.which("pdftoppm") is None:
        return {"text": "", "engine": "", "quality": "empty"}

    suffix = Path(source_name or "document.pdf").suffix or ".pdf"
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        pdf_path = temp_root / f"source{suffix}"
        pdf_path.write_bytes(payload)
        output_prefix = temp_root / "page"
        command = [
            "pdftoppm",
            "-png",
            "-r",
            str(_pdf_ocr_dpi()),
            str(pdf_path),
            str(output_prefix),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=180,
            )
        except Exception:
            return {"text": "", "engine": "", "quality": "empty"}

        page_paths = sorted(temp_root.glob("page-*.png"))[: _pdf_ocr_max_pages()]
        page_texts: list[str] = []
        first_engine = ""
        best_quality = "empty"

        for page_path in page_paths:
            evidence = extract_image_text_with_metadata(
                path=str(page_path),
                mime_type="image/png",
                payload=page_path.read_bytes(),
            )
            if evidence["text"]:
                page_texts.append(evidence["text"])
                if not first_engine:
                    first_engine = str(evidence["engine"] or "")
                if evidence["quality"] == "high":
                    best_quality = "high"
                elif evidence["quality"] == "medium" and best_quality not in {"high"}:
                    best_quality = "medium"
                elif evidence["quality"] == "low" and best_quality == "empty":
                    best_quality = "low"

        combined = _normalize_text("\n".join(page_texts))
        return {
            "text": combined,
            "engine": first_engine,
            "quality": best_quality if combined else "empty",
        }


def extract_pdf_text_with_metadata(payload: bytes, source_name: str = "") -> dict[str, Any]:
    try:
        native_text = _normalize_text(_extract_native_pdf_text(payload))
    except Exception:
        native_text = ""
    if _char_count(native_text) >= _pdf_native_text_min_chars():
        return {
            "text": native_text,
            "parser": "pypdf",
            "ocr_engine": "",
            "quality": _quality_for_text(native_text),
        }

    ocr_result = _extract_pdf_text_via_page_ocr(payload, source_name=source_name)
    ocr_text = _normalize_text(str(ocr_result.get("text", "")))
    ocr_engine = str(ocr_result.get("engine", "") or "")

    if _char_count(ocr_text) > _char_count(native_text):
        return {
            "text": ocr_text,
            "parser": f"pdf-ocr-{ocr_engine or 'unknown'}",
            "ocr_engine": ocr_engine,
            "quality": str(ocr_result.get("quality", "empty") or "empty"),
        }

    return {
        "text": native_text,
        "parser": "pypdf",
        "ocr_engine": "",
        "quality": _quality_for_text(native_text),
    }
