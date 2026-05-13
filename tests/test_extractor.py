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
