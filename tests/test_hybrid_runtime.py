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
