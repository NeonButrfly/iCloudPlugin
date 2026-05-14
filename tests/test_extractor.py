from icloud_index_service.services import extractor as extractor_module
from icloud_index_service.services.extractor import extract_text_content, summarize_text


def test_summarize_text_truncates_to_requested_length():
    source = "alpha beta gamma delta epsilon"

    assert summarize_text(source, 12) == "alpha beta g"


def test_extract_text_content_uses_text_parser_for_text_extensions():
    assert (
        extract_text_content(
            path="/Notes/Plan.md",
            mime_type="application/octet-stream",
            payload=b"project atlas",
        )
        == "project atlas"
    )


def test_extract_text_content_returns_empty_string_for_unsupported_types():
    assert (
        extract_text_content(
            path="/Archive/binary.bin",
            mime_type="application/octet-stream",
            payload=b"\x00\x01\x02",
        )
        == ""
    )


def test_extract_text_content_strips_nul_bytes_from_extracted_text(monkeypatch):
    monkeypatch.setattr(
        extractor_module,
        "extract_text_from_pdf_bytes",
        lambda payload: "before\x00after",
    )

    assert (
        extract_text_content(
            path="/Reports/report.pdf",
            mime_type="application/pdf",
            payload=b"%PDF-1.7 fake",
        )
        == "beforeafter"
    )


def test_extract_text_content_routes_common_code_and_markup_extensions_to_text_parser():
    for path in (
        "/Site/index.html",
        "/Styles/site.css",
        "/Config/app.yml",
        "/Calendar/event.ics",
        "/Code/main.ts",
        "/Code/view.tsx",
        "/Data/export.sql",
        "/Build/cache.tsbuildinfo",
    ):
        assert (
            extract_text_content(
                path=path,
                mime_type="application/octet-stream",
                payload=b"hello world",
            )
            == "hello world"
        )


def test_extract_text_content_routes_image_extensions_to_ocr(monkeypatch):
    calls: list[tuple[str, str, bytes]] = []

    def fake_ocr(*, path: str, mime_type: str, payload: bytes) -> str:
        calls.append((path, mime_type, payload))
        return "decoded image text"

    monkeypatch.setattr(extractor_module, "extract_text_from_image_bytes", fake_ocr)

    result = extract_text_content(
        path="/Photos/receipt.heic",
        mime_type="image/heic",
        payload=b"fake-image",
    )

    assert result == "decoded image text"
    assert calls == [("/Photos/receipt.heic", "image/heic", b"fake-image")]


def test_extract_text_content_keeps_video_files_metadata_only():
    assert (
        extract_text_content(
            path="/Videos/clip.mov",
            mime_type="video/quicktime",
            payload=b"not parsed",
        )
        == ""
    )
