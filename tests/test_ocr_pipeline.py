from packages.classification import ocr_pipeline


def test_extract_image_text_with_metadata_prefers_paddleocr(monkeypatch):
    monkeypatch.setattr(
        ocr_pipeline,
        "_extract_image_text_with_paddleocr",
        lambda **_: "Member ID 12345 claim summary",
    )
    monkeypatch.setattr(
        ocr_pipeline,
        "_extract_image_text_with_tesseract",
        lambda **_: "fallback text",
    )

    result = ocr_pipeline.extract_image_text_with_metadata(
        path="/Photos/claim.png",
        mime_type="image/png",
        payload=b"fake-image",
    )

    assert result["engine"] == "paddleocr"
    assert result["text"] == "Member ID 12345 claim summary"
    assert result["quality"] in {"medium", "high"}


def test_extract_pdf_text_with_metadata_uses_ocr_when_native_text_is_sparse(monkeypatch):
    monkeypatch.setattr(ocr_pipeline, "_extract_native_pdf_text", lambda payload: "")
    monkeypatch.setattr(
        ocr_pipeline,
        "_extract_pdf_text_via_page_ocr",
        lambda payload, source_name="": {
            "text": "Scanned reimbursement packet with receipts",
            "engine": "tesseract",
            "quality": "high",
        },
    )

    result = ocr_pipeline.extract_pdf_text_with_metadata(b"%PDF-1.7 scanned", source_name="packet.pdf")

    assert result["parser"] == "pdf-ocr-tesseract"
    assert result["text"] == "Scanned reimbursement packet with receipts"
    assert result["ocr_engine"] == "tesseract"


def test_extract_pdf_text_with_metadata_keeps_native_pdf_text_when_it_is_strong(monkeypatch):
    monkeypatch.setattr(
        ocr_pipeline,
        "_extract_native_pdf_text",
        lambda payload: "Native PDF text " * 20,
    )
    monkeypatch.setattr(
        ocr_pipeline,
        "_extract_pdf_text_via_page_ocr",
        lambda payload, source_name="": {
            "text": "OCR text that should not win",
            "engine": "tesseract",
            "quality": "low",
        },
    )

    result = ocr_pipeline.extract_pdf_text_with_metadata(b"%PDF-1.7 native", source_name="native.pdf")

    assert result["parser"] == "pypdf"
    assert result["ocr_engine"] == ""
    assert result["text"].startswith("Native PDF text")
