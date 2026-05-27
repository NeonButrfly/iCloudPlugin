from __future__ import annotations

import json
from pathlib import Path

from apps.classifier import hybrid_runtime


def test_build_feature_text_includes_retrieval_metadata():
    feature_text = hybrid_runtime.build_feature_text(
        {
            "filename": "claim.pdf",
            "extension": ".pdf",
            "parser": "pdftotext",
            "heuristic_primary": "medical",
            "taxonomy_candidates": ["medical", "appeal"],
            "entity_summary": "organizations: Aetna; identifiers: claim id: EDPDK70ZX00",
            "topic_summary": "medical, insurance, appeal",
            "retrieval_terms": ["aetna", "appeal", "claim id"],
            "retrieval_text": "Aetna appeal packet for insurance review",
            "text_preview": "Sparse OCR text",
        }
    )

    assert "topics medical, insurance, appeal" in feature_text
    assert "entities organizations: Aetna" in feature_text
    assert "retrieval-terms aetna appeal claim id" in feature_text
    assert "retrieval-text Aetna appeal packet for insurance review" in feature_text


def test_build_feature_text_includes_ocr_and_extraction_quality_metadata():
    feature_text = hybrid_runtime.build_feature_text(
        {
            "filename": "scan.png",
            "extension": ".png",
            "parser": "image-ocr-paddleocr",
            "heuristic_primary": "invoice",
            "taxonomy_candidates": ["invoice", "receipt"],
            "ocr_engine": "paddleocr",
            "ocr_quality": "high",
            "ocr_char_count": 184,
            "extraction_quality": "high",
            "text_preview": "Invoice total due paid amount provider account number",
        }
    )

    assert "ocr-engine paddleocr" in feature_text
    assert "ocr-quality high" in feature_text
    assert "ocr-chars 184" in feature_text
    assert "extraction-quality high" in feature_text


def test_build_training_rows_from_runtime_carries_extraction_metadata(tmp_path: Path):
    manifest_path = tmp_path / "manifest.jsonl"
    comparisons_path = tmp_path / "comparisons.jsonl"
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "source_path": "/vault/scan.png",
                "timing": {
                    "parser": "image-ocr-paddleocr",
                    "ocr_engine": "paddleocr",
                    "ocr_quality": "high",
                    "ocr_chars": 184,
                    "extraction_quality": "high",
                },
                "classification": {
                    "primary_label": "invoice",
                    "summary": "Invoice for medical provider",
                    "reason": "OCR text was strong.",
                    "ocr_engine": "paddleocr",
                    "ocr_quality": "high",
                    "ocr_char_count": 184,
                    "extraction_quality": "high",
                },
                "hybrid": {
                    "decision": {"live_source": "heuristic-fast-path", "selected_primary_hint": "invoice"},
                    "taxonomy_candidates": ["invoice", "receipt"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    comparisons_path.write_text("", encoding="utf-8")

    rows = hybrid_runtime.build_training_rows_from_runtime(
        manifest_path=manifest_path,
        corrections_path=tmp_path / "corrections.jsonl",
        examples_path=tmp_path / "examples.jsonl",
        comparisons_path=comparisons_path,
    )

    assert rows[0]["ocr_engine"] == "paddleocr"
    assert rows[0]["ocr_quality"] == "high"
    assert rows[0]["ocr_char_count"] == 184
    assert rows[0]["extraction_quality"] == "high"


def test_run_autonomous_shadow_cycle_respects_disabled_retrain_and_threshold_updates(
    tmp_path: Path,
    monkeypatch,
):
    queue_dir = tmp_path / "shadow-queue"
    queue_dir.mkdir(parents=True)
    comparisons_path = tmp_path / "shadow-comparisons.jsonl"
    model_path = tmp_path / "lightgbm.joblib"
    report_path = tmp_path / "lightgbm-report.json"

    job_path = queue_dir / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "filename": "claim.pdf",
                "extension": ".pdf",
                "parser": "pdftotext",
                "heuristic_result": {"primary_label": "medical", "confidence": 0.95},
                "lightgbm_result": {"top_label": "medical", "top_probability": 0.91},
                "live_result": {"primary_label": "medical", "confidence": 0.95},
                "taxonomy_candidates": ["medical", "appeal"],
                "text_preview": "Appeal packet",
                "entity_summary": "organizations: Aetna",
                "topic_summary": "medical, insurance, appeal",
                "retrieval_terms": ["aetna", "appeal"],
                "retrieval_text": "Aetna appeal packet",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        hybrid_runtime,
        "write_readiness_report",
        lambda gating_config=None: {"ok": True, "real_ingestion_allowed": False},
    )

    result = hybrid_runtime.run_autonomous_shadow_cycle(
        shadow_classifier=lambda job: {"primary_label": "medical", "confidence": 0.99},
        gating_config={
            **hybrid_runtime.DEFAULT_HYBRID_GATING,
            "shadow_batch_size": 1,
            "auto_threshold_update_enabled": False,
            "auto_retrain_enabled": False,
        },
        queue_dir=queue_dir,
        comparisons_path=comparisons_path,
        model_path=model_path,
        report_path=report_path,
    )

    assert result["processed"] == 1
    assert result["updates"]["reason"] == "auto-threshold-update-disabled"
    assert result["retrain"]["reason"] == "auto-retrain-disabled"
    comparisons = hybrid_runtime.read_jsonl(comparisons_path)
    assert comparisons[0]["entity_summary"] == "organizations: Aetna"
    assert comparisons[0]["retrieval_terms"] == ["aetna", "appeal"]


def test_build_readiness_report_uses_reviewed_examples_as_bootstrap_feedback(tmp_path: Path):
    model_path = tmp_path / "lightgbm.joblib"
    model_path.write_bytes(b"model")
    examples_path = tmp_path / "examples.jsonl"
    rows = []
    labels = [
        ("appeal", ".docx"),
        ("invoice", ".pdf"),
        ("receipt", ".csv"),
        ("medical", ".png"),
        ("legal", ".html"),
        ("benefits", ".txt"),
        ("claim", ".xlsx"),
        ("tax", ".jpg"),
        ("manual", ".md"),
        ("contract", ".pptx"),
    ]
    for index, (label, extension) in enumerate(labels, start=1):
        rows.append(
            {
                "filename": f"sample-{index}{extension}",
                "source_filename": f"sample-{index}{extension}",
                "correct_label": label,
                "old_label": "unknown",
                "confidence": 0.99,
                "summary": f"Reviewed {label} example",
                "secondary_labels": ["reviewed"],
            }
        )
    examples_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    report = hybrid_runtime.build_readiness_report(
        gating_config={
            **hybrid_runtime.DEFAULT_HYBRID_GATING,
            "allow_real_ingestion": True,
        },
        comparisons_path=tmp_path / "shadow-comparisons.jsonl",
        queue_dir=tmp_path / "shadow-queue",
        model_path=model_path,
        examples_path=examples_path,
        corrections_path=tmp_path / "corrections.jsonl",
    )

    assert report["model_exists"] is True
    assert report["teacher_approved_rows"] == 10
    assert report["teacher_approval_rate"] == 1.0
    assert report["teacher_agreement_rate"] == 1.0
    assert report["real_ingestion_allowed"] is True
    assert report["feedback_sources"]["reviewed-example"] == 10


def test_maybe_retrain_from_shadow_data_uses_bootstrap_examples(tmp_path: Path):
    examples_path = tmp_path / "examples.jsonl"
    examples_path.write_text(
        "".join(
            json.dumps(
                {
                    "filename": f"reviewed-{index}.pdf",
                    "source_filename": f"reviewed-{index}.pdf",
                    "correct_label": label,
                    "old_label": "unknown",
                    "confidence": 0.98,
                    "summary": f"Reviewed {label} training example",
                    "secondary_labels": ["reviewed"],
                }
            )
            + "\n"
            for index, label in enumerate(["appeal", "invoice", "medical", "legal"], start=1)
        ),
        encoding="utf-8",
    )
    model_path = tmp_path / "lightgbm.joblib"
    report_path = tmp_path / "lightgbm-report.json"

    result = hybrid_runtime.maybe_retrain_from_shadow_data(
        comparisons_path=tmp_path / "shadow-comparisons.jsonl",
        examples_path=examples_path,
        corrections_path=tmp_path / "corrections.jsonl",
        model_path=model_path,
        report_path=report_path,
        min_rows=3,
    )

    assert result["retrained"] is True
    assert result["teacher_approved_rows"] == 4
    assert result["feedback_sources"]["reviewed-example"] == 4
    assert model_path.exists()
    assert report_path.exists()
