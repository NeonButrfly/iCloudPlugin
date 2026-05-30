from __future__ import annotations

import json


def test_find_reviewed_label_override_ignores_noop_manual_move_rows(tmp_path, monkeypatch):
    from apps.classifier import category_manager

    source_path = "/srv/cloud-vault/mirrors/icloud/Scanned/receipt.pdf"
    manual_feedback_path = tmp_path / "manual-note-feedback.jsonl"
    manual_feedback_path.write_text(
        "".join(
            [
                json.dumps(
                    {
                        "source_path": source_path,
                        "correct_label": "receipt",
                        "old_label": "financial",
                        "review_status": "manual-note-move",
                        "feedback_strength": "strong",
                        "recorded_at": "2026-05-29T20:59:04-08:00",
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "source_path": source_path,
                        "correct_label": "financial",
                        "old_label": "financial",
                        "review_status": "manual-note-move",
                        "feedback_strength": "strong",
                        "recorded_at": "2026-05-29T21:09:48-08:00",
                    }
                )
                + "\n",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(category_manager, "MANUAL_NOTE_FEEDBACK_FILE", manual_feedback_path)
    monkeypatch.setattr(category_manager, "CORRECTIONS_FILE", tmp_path / "corrections.jsonl")
    monkeypatch.setattr(category_manager, "EXAMPLES_FILE", tmp_path / "examples.jsonl")

    override = category_manager.find_reviewed_label_override(source_path=source_path)

    assert override is not None
    assert override["correct_label"] == "receipt"
