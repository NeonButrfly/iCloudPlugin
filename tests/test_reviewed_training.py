from __future__ import annotations

import json
from pathlib import Path

from apps.classifier.external_taxonomy import build_external_taxonomy_aliases, match_external_taxonomy_candidates
from apps.classifier.reviewed_training import import_reviewed_examples_from_manifest


def test_external_taxonomy_prune_rules_remove_noisy_aliases():
    payload = build_external_taxonomy_aliases(
        [
            {
                "name": "test_static",
                "enabled": True,
                "kind": "document",
                "parser": "static",
                "labels": ["box", "form", "school", "medical", "business forms and receipts", "invoice"],
            }
        ],
        prune_rules={
            "blocked_aliases_by_label": {
                "product-photo": ["box"],
                "form": ["form"],
                "school": ["school"],
                "medical": ["medical"],
            }
        },
    )

    aliases = payload["label_aliases"]
    assert "box" not in aliases.get("product-photo", [])
    assert "form" not in aliases.get("form", [])
    assert "school" not in aliases.get("school", [])
    assert "medical" not in aliases.get("medical", [])
    assert "business forms and receipts" in aliases.get("form", [])
    assert "invoice" in aliases.get("invoice", [])


def test_match_external_taxonomy_candidates_honors_pruned_aliases():
    aliases = {
        "product-photo": ["box"],
        "invoice": ["invoice"],
    }

    matches = match_external_taxonomy_candidates(
        "shipping box with invoice attached",
        aliases=aliases,
        prune_rules={"blocked_aliases_by_label": {"product-photo": ["box"]}},
        limit=4,
    )

    assert all(match["label"] != "product-photo" for match in matches)
    assert any(match["label"] == "invoice" for match in matches)


def test_import_reviewed_examples_from_manifest_writes_weak_bucket_rows(tmp_path):
    manifest_path = tmp_path / "reviewed.manifest.json"
    examples_path = tmp_path / "examples.jsonl"
    report_path = tmp_path / "examples-report.json"
    manifest_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "file_name": "appeal.docx",
                        "source_path": "Appeals/appeal.docx",
                        "final_label": "appeal",
                        "queue_label": "insurance",
                        "secondary_labels": "legal, medical",
                        "reason": "Appeal packet for denied health claim.",
                        "evidence_excerpt": "appeal claim coverage denial patient",
                        "heuristic_label": "appeal",
                        "review_status": "confirmed",
                    },
                    {
                        "file_name": "invoice.pdf",
                        "source_path": "Billing/invoice.pdf",
                        "final_label": "invoice",
                        "queue_label": "financial",
                        "secondary_labels": "receipt",
                        "reason": "Vendor invoice with amount due.",
                        "evidence_excerpt": "invoice vendor billing statement amount due",
                        "heuristic_label": "invoice",
                        "review_status": "needs_review",
                    },
                    {
                        "file_name": "manual.pdf",
                        "source_path": "Docs/manual.pdf",
                        "final_label": "manual",
                        "queue_label": "manual",
                        "secondary_labels": "",
                        "reason": "Manual that should be ignored by weak-bucket importer.",
                        "evidence_excerpt": "manual instructions user guide",
                        "heuristic_label": "manual",
                        "review_status": "confirmed",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = import_reviewed_examples_from_manifest(
        manifest_path=manifest_path,
        examples_path=examples_path,
        report_path=report_path,
        target_labels={"appeal": 10, "invoice": 10},
    )

    rows = [json.loads(line) for line in examples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert report["imported_rows"] == 2
    assert report["label_counts"] == {"appeal": 1, "invoice": 1}
    assert len(rows) == 2
    assert rows[0]["correct_label"] == "appeal"
    assert rows[0]["old_label"] == "insurance"
    assert rows[1]["correct_label"] == "invoice"
    assert rows[1]["secondary_labels"] == ["receipt"]
    assert "amount due" in rows[1]["summary"]
