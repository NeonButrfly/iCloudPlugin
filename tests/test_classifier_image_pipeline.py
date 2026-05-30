from pathlib import Path

from apps.classifier import classify_to_obsidian as classifier_module


def test_parse_document_uses_pdf_ocr_fallback_when_fast_pdf_text_is_sparse(tmp_path: Path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")

    monkeypatch.setattr(
        classifier_module,
        "parse_pdf_fast",
        lambda path: (_ for _ in ()).throw(RuntimeError("sparse text")),
    )
    monkeypatch.setattr(
        classifier_module,
        "parse_pdf_with_ocr_fallback",
        lambda path: (
            "Scanned appeal packet",
            "pdf-ocr-tesseract",
            {
                "ocr_engine": "tesseract",
                "ocr_quality": "medium",
                "ocr_char_count": 20,
                "extraction_quality": "medium",
            },
        ),
    )

    markdown, parser_name, extraction_metadata = classifier_module.parse_document(pdf_path, tmp_path / "work")

    assert markdown == "Scanned appeal packet"
    assert parser_name == "pdf-ocr-tesseract"
    assert extraction_metadata["ocr_engine"] == "tesseract"


def test_classify_image_routes_rich_ocr_text_through_document_pipeline(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "receipt.png"
    image_path.write_bytes(b"fake-image")

    monkeypatch.setattr(
        classifier_module,
        "extract_image_text_with_metadata",
        lambda **_: {
            "text": "Invoice total due provider billed amount appeal contact information",
            "engine": "paddleocr",
            "quality": "high",
            "char_count": 64,
        },
    )
    monkeypatch.setattr(
        classifier_module,
        "classify_document_fast",
        lambda **_: {"primary_label": "invoice", "confidence": 0.95},
    )
    monkeypatch.setattr(
        classifier_module,
        "resolve_hybrid_document_decision",
        lambda **kwargs: (
            {
                "primary_label": "invoice",
                "secondary_labels": ["financial"],
                "confidence": 0.97,
                "summary": "OCR-first invoice classification",
                "reason": "OCR text was strong enough to avoid vision fallback.",
            },
            {
                "decision": {"live_source": "heuristic-fast-path"},
                "taxonomy_candidates": ["invoice", "financial"],
                "extraction": kwargs.get("extraction_metadata", {}),
            },
        ),
    )

    classification, hybrid_meta, markdown = classifier_module.classify_image(
        source_path=image_path,
        categories=["invoice", "financial", "photo", "unknown"],
        ollama_url="http://example.invalid",
        model="qwen2.5:3b",
        vision_model="qwen2.5vl:3b",
        max_chars=4000,
    )

    assert classification["primary_label"] == "invoice"
    assert classification["ocr_engine"] == "paddleocr"
    assert classification["extraction_quality"] == "high"
    assert hybrid_meta["decision"]["live_source"] == "heuristic-fast-path"
    assert hybrid_meta["extraction"]["ocr_engine"] == "paddleocr"
    assert "Invoice total due" in markdown


def test_classify_image_falls_back_to_vision_when_ocr_text_is_sparse(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"fake-image")

    monkeypatch.setattr(
        classifier_module,
        "extract_image_text_with_metadata",
        lambda **_: {
            "text": "hi",
            "engine": "tesseract",
            "quality": "low",
            "char_count": 2,
        },
    )
    monkeypatch.setattr(
        classifier_module,
        "classify_image_vision",
        lambda **_: {
            "primary_label": "photo",
            "secondary_labels": ["reference-image"],
            "confidence": 0.72,
            "summary": "Vision fallback result",
            "reason": "OCR evidence was too sparse.",
        },
    )

    classification, hybrid_meta, markdown = classifier_module.classify_image(
        source_path=image_path,
        categories=["photo", "reference-image", "unknown"],
        ollama_url="http://example.invalid",
        model="qwen2.5:3b",
        vision_model="qwen2.5vl:3b",
        max_chars=4000,
    )

    assert classification["primary_label"] == "photo"
    assert classification["ocr_engine"] == "tesseract"
    assert classification["extraction_quality"] == "low"
    assert hybrid_meta is None
    assert markdown == ""


def test_normalize_vault_classification_recovers_primary_from_hybrid_fallback():
    normalized = classifier_module.normalize_vault_classification(
        {
            "summary": "Claims export from insurer.",
            "reason": "The model returned a malformed structured payload.",
            "confidence": "",
        },
        candidate_categories=["medical", "insurance", "needs-review"],
        fallback_primary="insurance",
        fallback_confidence=0.95,
        fallback_secondary=["medical"],
    )

    assert normalized["primary_label"] == "insurance"
    assert normalized["secondary_labels"] == ["medical"]
    assert normalized["confidence"] == 0.69
    assert normalized["recommended_action"] == "review"


def test_extract_json_accepts_fenced_json_payload():
    payload = """```json
    {
      "primary_label": "invoice",
      "secondary_labels": ["financial"],
      "confidence": 0.95
    }
    ```"""

    result = classifier_module.extract_json(payload)

    assert result["primary_label"] == "invoice"
    assert result["secondary_labels"] == ["financial"]


def test_resolve_hybrid_document_decision_uses_exact_reviewed_override(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "receipt.pdf"
    source_path.write_bytes(b"%PDF-1.7 fake")

    monkeypatch.setattr(classifier_module, "build_retrieval_metadata", lambda **_: {})
    monkeypatch.setattr(
        classifier_module,
        "select_candidate_categories",
        lambda **_: ["receipt", "financial", "needs-review"],
    )
    monkeypatch.setattr(
        classifier_module,
        "find_reviewed_label_override",
        lambda **_: {
            "source_path": str(source_path),
            "correct_label": "receipt",
            "secondary_labels": ["financial"],
            "summary": "Manual correction moved this exact file to receipt.",
            "note": "manual-note-move:01 Classified/receipt/receipt.md",
            "review_status": "manual-note-move",
            "feedback_strength": "strong",
        },
        raising=False,
    )
    monkeypatch.setattr(
        classifier_module,
        "predict_lightgbm_result",
        lambda **_: {
            "top_label": "financial",
            "top_probability": 0.97,
            "needs_llm_probability": 0.02,
            "disagreement_risk": 0.01,
        },
    )

    llm_calls = {"count": 0}

    def _unexpected_inline_llm(**_kwargs):
        llm_calls["count"] += 1
        return {
            "primary_label": "financial",
            "secondary_labels": [],
            "confidence": 0.4,
            "summary": "Should not be used.",
            "reason": "inline llm",
        }

    monkeypatch.setattr(classifier_module, "classify_markdown", _unexpected_inline_llm)

    classification, hybrid_meta = classifier_module.resolve_hybrid_document_decision(
        source_path=source_path,
        markdown="Home improvement store receipt total amount paid by card.",
        parser_name="pdftotext",
        categories=["receipt", "financial", "needs-review"],
        heuristic_result={"primary_label": "financial", "confidence": 0.91},
        ollama_url="http://example.invalid",
        model="qwen2.5:3b",
        max_chars=4000,
    )

    assert llm_calls["count"] == 0
    assert classification["primary_label"] == "receipt"
    assert classification["secondary_labels"] == ["financial"]
    assert classification["confidence"] == 1.0
    assert hybrid_meta["decision"]["live_source"] == "manual-correction-override"
    assert hybrid_meta["decision"]["decision_reason"] == "exact-source-reviewed-feedback"


def test_classify_markdown_passes_source_path_to_relevant_examples(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "receipt.pdf"
    source_path.write_bytes(b"%PDF-1.7 fake")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        classifier_module,
        "select_candidate_categories",
        lambda **_: ["receipt", "financial"],
    )

    def _capture_examples(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(classifier_module, "load_relevant_examples", _capture_examples)
    monkeypatch.setattr(
        classifier_module,
        "ollama_chat",
        lambda **_: '{"primary_label":"receipt","secondary_labels":[],"confidence":0.8,"summary":"Receipt","reason":"Contains totals.","sensitive_flags":["financial"],"recommended_action":"keep","file_date_guess":"unknown","language":"English"}',
    )

    result = classifier_module.classify_markdown(
        markdown="Receipt total amount paid.",
        source_path=source_path,
        categories=["receipt", "financial"],
        ollama_url="http://example.invalid",
        model="qwen2.5:3b",
        max_chars=4000,
    )

    assert result["primary_label"] == "receipt"
    assert captured["source_path"] == source_path
