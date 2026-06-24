from __future__ import annotations

import json
from pathlib import Path

from apps.classifier import hybrid_runtime
from apps.classifier.index_training import (
    build_stratified_training_rows,
    build_taxonomy_training_dataset,
    resolve_index_database_url,
)
from apps.classifier.label_map import canonicalize_label


def _make_record(
    file_id: int,
    *,
    provider: str,
    name: str,
    path_tail: str,
    mime_type: str,
    extension: str = "",
    content_text: str = "",
) -> dict[str, object]:
    return {
        "id": file_id,
        "external_id": f"filesystem::/{provider}/{path_tail}",
        "name": name,
        "path": f"/{provider}/{path_tail}",
        "mime_type": mime_type,
        "extension": extension,
        "content_text": content_text,
    }


def test_build_stratified_training_rows_creates_all_requested_buckets():
    records = [
        _make_record(1, provider="icloud", name="medical_claim.pdf", path_tail="Medical/medical_claim.pdf", mime_type="application/pdf", extension="pdf", content_text="medical claim appeal benefits"),
        _make_record(2, provider="icloud", name="family_photo.jpg", path_tail="Photos/family_photo.jpg", mime_type="image/jpeg", extension="jpg", content_text="family photo"),
        _make_record(3, provider="icloud", name="random_notes.txt", path_tail="Notes/random_notes.txt", mime_type="text/plain", extension="txt", content_text="misc text with no clue"),
        _make_record(4, provider="google1", name="invoice_april.pdf", path_tail="Finance/invoice_april.pdf", mime_type="application/pdf", extension="pdf", content_text="invoice payment balance"),
        _make_record(5, provider="google1", name="tax_return.docx", path_tail="Taxes/tax_return.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", extension="docx", content_text="tax return 1099"),
        _make_record(6, provider="google1", name="roadmap.md", path_tail="Work/roadmap.md", mime_type="text/markdown", extension="md", content_text="# roadmap\nproject update"),
        _make_record(7, provider="google2", name="spreadsheet.csv", path_tail="Sheets/spreadsheet.csv", mime_type="text/csv", extension="csv", content_text="column1,column2\n1,2"),
        _make_record(8, provider="google2", name="ui_screenshot.png", path_tail="Screens/ui_screenshot.png", mime_type="image/png", extension="png", content_text="ui screenshot with error dialog"),
        _make_record(9, provider="google2", name="insurance_letter.pdf", path_tail="Insurance/insurance_letter.pdf", mime_type="application/pdf", extension="pdf", content_text="insurance claim appeal letter"),
        _make_record(10, provider="google2", name="plain_image.heic", path_tail="Photos/plain_image.heic", mime_type="image/heic", extension="heic", content_text=""),
        _make_record(11, provider="google1", name="legal_agreement.pdf", path_tail="Legal/legal_agreement.pdf", mime_type="application/pdf", extension="pdf", content_text="contract agreement clause"),
        _make_record(12, provider="icloud", name="sunscreen_receipt.pdf", path_tail="Receipts/sunscreen_receipt.pdf", mime_type="application/pdf", extension="pdf", content_text="sunscreen receipt fsa"),
        _make_record(13, provider="google2", name="presentation.pptx", path_tail="Decks/presentation.pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", extension="pptx", content_text="project presentation"),
        _make_record(14, provider="icloud", name="generic_image.png", path_tail="Photos/generic_image.png", mime_type="image/png", extension="png", content_text=""),
        _make_record(15, provider="google1", name="readme.html", path_tail="Docs/readme.html", mime_type="text/html", extension="html", content_text="<html><body>technical note</body></html>"),
        _make_record(16, provider="google1", name="archive.zip", path_tail="Archives/archive.zip", mime_type="application/zip", extension="zip", content_text=""),
    ]

    rows, report = build_stratified_training_rows(
        records,
        sample_split={
            "provider_balanced": 3,
            "sensitive_keyword": 3,
            "low_confidence": 2,
            "ambiguous": 2,
            "file_type_coverage": 2,
        },
        target_sample_size=12,
        seed=13,
    )

    assert len(rows) == 12
    assert report["selected_sample_size"] == 12
    assert sum(report["realized_bucket_counts"].values()) == 12
    assert report["excluded_archive_rows"] == 1
    assert report["excluded_archive_extensions"] == {"zip": 1}
    assert all(row["extension"] != "zip" for row in rows)
    assert {row["sample_bucket"] for row in rows}
    assert any(row["provider"] == "icloud" for row in rows)
    assert any(row["provider"] == "google1" for row in rows)
    assert any(row["provider"] == "google2" for row in rows)
    assert any(row["accepted_primary"] in {"medical", "insurance", "tax", "legal"} for row in rows)
    assert any(row["file_type_group"] == "images" for row in rows)
    assert any(row["used_inline_llm"] for row in rows)


def test_ensure_lightgbm_model_falls_back_to_index_training(tmp_path, monkeypatch):
    model_path = tmp_path / "lightgbm-classifier.joblib"
    report_path = tmp_path / "lightgbm-training-report.json"

    monkeypatch.setattr(hybrid_runtime, "build_training_rows_from_runtime", lambda: [])

    called = {}

    def fake_train_lightgbm_from_index(*, database_url, model_path, report_path, sample_split=None, seed=7):
        called["database_url"] = database_url
        called["model_path"] = model_path
        called["report_path"] = report_path
        called["sample_split"] = sample_split
        called["seed"] = seed
        model_path.write_text("model", encoding="utf-8")
        report_path.write_text("{}", encoding="utf-8")
        return {"ok": True, "kind": "hybrid-lightgbm-v1", "training_rows": 12}

    monkeypatch.setattr("apps.classifier.index_training.train_lightgbm_from_index", fake_train_lightgbm_from_index)

    result = hybrid_runtime.ensure_lightgbm_model(
        model_path=model_path,
        report_path=report_path,
        training_source="index",
        index_database_url="postgresql://example/test",
    )

    assert result["ok"] is True
    assert result["created"] is True
    assert result["training_source"] == "index"
    assert called["database_url"] == "postgresql://example/test"
    assert called["model_path"] == model_path
    assert called["report_path"] == report_path


def test_resolve_index_database_url_prefers_index_database_url(monkeypatch):
    monkeypatch.setenv("INDEX_DATABASE_URL", "postgresql://example/index")
    assert resolve_index_database_url() == "postgresql://example/index"


def test_canonical_label_map_collapses_related_classes():
    assert canonicalize_label("appeal") == "insurance"
    assert canonicalize_label("claim") == "insurance"
    assert canonicalize_label("medical-receipt") == "financial"
    assert canonicalize_label("ui-screenshot") == "screenshot"
    assert canonicalize_label("unknown") == "unknown"


def test_choose_live_decision_aligns_on_canonical_labels():
    gating = hybrid_runtime.load_hybrid_gating_config()
    decision = hybrid_runtime.choose_live_decision(
        {"primary_label": "appeal", "confidence": 0.97},
        {"top_label": "claim", "top_probability": 0.98, "needs_llm_probability": 0.1, "disagreement_risk": 0.1},
        gating,
        ["appeal", "claim", "insurance"],
    )

    assert decision["use_inline_llm"] is False
    assert decision["live_source"] == "heuristic-fast-path"
    assert decision["selected_primary_hint"] == "insurance"


def test_build_taxonomy_training_dataset_uses_classifier_state_and_teacher_signals():
    records = [
        {
            **_make_record(
                21,
                provider="icloud",
                name="benefits_appeal.pdf",
                path_tail="Benefits/benefits_appeal.pdf",
                mime_type="application/pdf",
                extension="pdf",
                content_text="medical appeal insurance benefits claim form",
            ),
            "submission_status": "completed",
            "classifier_note_path": "02 Needs Review/benefits_appeal.md",
            "classifier_manifest_record": json.dumps({"primary_label": "needs-review"}),
            "state_primary_label": "needs-review",
            "state_summary": "Needs a closer read.",
            "state_confidence": 0.61,
            "state_reasoning": "Low confidence result.",
            "entity_summary": "organizations: Moda",
            "topic_summary": "insurance, appeal",
            "retrieval_terms_json": json.dumps(["appeal", "benefits", "claim"]),
            "retrieval_text": "appeal benefits claim",
            "response_payload_json": json.dumps(
                {
                    "primary_label": "needs-review",
                    "secondary_labels": ["appeal", "benefits"],
                    "summary": "Needs a closer read.",
                    "reasoning": "Low confidence result.",
                }
            ),
            "last_error": "",
        },
        {
            **_make_record(
                22,
                provider="google1",
                name="invoice_april.pdf",
                path_tail="Finance/invoice_april.pdf",
                mime_type="application/pdf",
                extension="pdf",
                content_text="invoice payment balance due account summary",
            ),
            "submission_status": "completed",
            "classifier_note_path": "01 Classified/invoice_april.md",
            "classifier_manifest_record": json.dumps({"primary_label": "invoice"}),
            "state_primary_label": "invoice",
            "state_summary": "Invoice for April.",
            "state_confidence": 0.94,
            "state_reasoning": "Clear invoice terminology.",
            "entity_summary": "vendors: Utility Company",
            "topic_summary": "invoice, financial",
            "retrieval_terms_json": json.dumps(["invoice", "payment"]),
            "retrieval_text": "invoice payment balance due",
            "response_payload_json": json.dumps(
                {
                    "primary_label": "invoice",
                    "secondary_labels": ["financial"],
                    "summary": "Invoice for April.",
                    "reasoning": "Clear invoice terminology.",
                }
            ),
            "last_error": "",
        },
    ]

    rows, report = build_taxonomy_training_dataset(records)

    assert len(rows) == 2
    first = rows[0]
    assert first["classifier_primary_label"] == "needs-review"
    assert first["classifier_secondary_labels"] == ["insurance"]
    assert first["review_recommended"] is True
    assert "classifier-review-label" in first["review_reasons"]
    assert "classifier-low-confidence" in first["review_reasons"]
    assert first["training_target_label"] == first["teacher_label"]
    assert "insurance" in first["taxonomy_candidates"]
    assert first["retrieval_terms"] == ["appeal", "benefits", "claim"]

    second = rows[1]
    assert second["classifier_primary_label"] == "financial"
    assert second["review_recommended"] is False
    assert second["training_target_label"] == "financial"

    assert report["total_rows"] == 2
    assert report["rows_with_classification_state"] == 2
    assert report["review_recommended_rows"] == 1
    assert report["provider_counts"] == {"google1": 1, "icloud": 1}
    assert report["submission_status_counts"] == {"completed": 2}
    assert report["classifier_label_counts"]["financial"] == 1
    assert report["classifier_label_counts"]["needs-review"] == 1
