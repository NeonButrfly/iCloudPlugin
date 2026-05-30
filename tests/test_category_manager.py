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


def test_find_reviewed_label_override_prefers_exact_source_over_newer_filename_collision(tmp_path, monkeypatch):
    from apps.classifier import category_manager

    source_path = "/srv/cloud-vault/mirrors/google1/Appeal.docx"
    filename = "Appeal.docx"
    manual_feedback_path = tmp_path / "manual-note-feedback.jsonl"
    manual_feedback_path.write_text(
        json.dumps(
            {
                "source_path": source_path,
                "filename": filename,
                "correct_label": "appeal",
                "old_label": "medical",
                "review_status": "manual-note-move",
                "feedback_strength": "strong",
                "recorded_at": "2026-05-29T23:17:24-08:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    examples_path = tmp_path / "examples.jsonl"
    examples_path.write_text(
        json.dumps(
            {
                "source_path": "/icloud/untitled folder/sort/combined/Appeal.docx",
                "filename": filename,
                "correct_label": "denial-letter",
                "old_label": "personal",
                "review_status": "codex_sanity_checked",
                "recorded_at": "2026-05-29T23:25:00-08:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(category_manager, "MANUAL_NOTE_FEEDBACK_FILE", manual_feedback_path)
    monkeypatch.setattr(category_manager, "CORRECTIONS_FILE", tmp_path / "corrections.jsonl")
    monkeypatch.setattr(category_manager, "EXAMPLES_FILE", examples_path)

    override = category_manager.find_reviewed_label_override(
        source_path=source_path,
        filename=filename,
    )

    assert override is not None
    assert override["source_path"] == source_path
    assert override["correct_label"] == "appeal"


def test_find_reviewed_label_override_keeps_same_primary_secondary_label_correction(tmp_path, monkeypatch):
    from apps.classifier import category_manager

    source_path = "/srv/cloud-vault/mirrors/google1/Appeal.docx"
    manual_feedback_path = tmp_path / "manual-note-feedback.jsonl"
    manual_feedback_path.write_text(
        json.dumps(
            {
                "source_path": source_path,
                "filename": "Appeal.docx",
                "correct_label": "medical",
                "old_label": "medical",
                "secondary_labels": ["appeal"],
                "old_secondary_labels": [],
                "review_status": "manual-note-move",
                "feedback_strength": "strong",
                "recorded_at": "2026-05-29T23:40:00-08:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(category_manager, "MANUAL_NOTE_FEEDBACK_FILE", manual_feedback_path)
    monkeypatch.setattr(category_manager, "CORRECTIONS_FILE", tmp_path / "corrections.jsonl")
    monkeypatch.setattr(category_manager, "EXAMPLES_FILE", tmp_path / "examples.jsonl")

    override = category_manager.find_reviewed_label_override(source_path=source_path)

    assert override is not None
    assert override["correct_label"] == "medical"
    assert override["secondary_labels"] == ["appeal"]
