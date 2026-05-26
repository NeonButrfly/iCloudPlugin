from __future__ import annotations

import json

from apps.classifier.example_mining import is_sane_example_candidate, mine_example_corpus


def test_is_sane_example_candidate_rejects_placeholder_appeal():
    ok, reason = is_sane_example_candidate(
        "appeal",
        {
            "name": "05212026160747_(DocTitle).pdf",
            "path": "",
            "content_text": "queue=appeal",
            "mime_type": "application/pdf",
            "extension": "pdf",
        },
        {
            "teacher_confidence": 1.0,
            "teacher_primary": "appeal",
            "naive_label": "appeal",
        },
    )

    assert ok is False
    assert reason in {"missing-source-path", "generic-placeholder-signal"}


def test_is_sane_example_candidate_accepts_strong_invoice():
    ok, reason = is_sane_example_candidate(
        "invoice",
        {
            "name": "invoice_april.pdf",
            "path": "/google1/Finance/invoice_april.pdf",
            "content_text": "Vendor invoice with amount due, statement date, and total payment terms.",
            "mime_type": "application/pdf",
            "extension": "pdf",
        },
        {
            "teacher_confidence": 0.88,
            "teacher_primary": "invoice",
            "naive_label": "financial",
        },
    )

    assert ok is True
    assert reason == "ok"


def test_is_sane_example_candidate_rejects_confirmation_receipt_as_receipt():
    ok, reason = is_sane_example_candidate(
        "receipt",
        {
            "name": "OCR_confirmation.pdf",
            "path": "/icloud/Scanned/OCR Complaint/OCR_confirmation.pdf",
            "content_text": "Welcome Complaint Form Confirmation Receipt Number: 28758885 Thank you for contacting the Office for Civil Rights.",
            "mime_type": "application/pdf",
            "extension": "pdf",
        },
        {
            "teacher_confidence": 0.74,
            "teacher_primary": "receipt",
            "teacher_ranked_labels": ["receipt", "letter"],
            "naive_label": "receipt",
        },
    )

    assert ok is False
    assert reason == "excluded-term"


def test_is_sane_example_candidate_rejects_school_essay_as_claim():
    ok, reason = is_sane_example_candidate(
        "claim",
        {
            "name": "PHIL_A201_Midterm.docx",
            "path": "/icloud/sort/PHIL_A201_Midterm.docx",
            "content_text": "Kay Mayers Professor Rowe PHIL A201 The Problem of Evil During this semester we examined several philosophical claims and arguments.",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "extension": "docx",
        },
        {
            "teacher_confidence": 0.8,
            "teacher_primary": "claim",
            "teacher_ranked_labels": ["claim", "school"],
            "naive_label": "claim",
        },
    )

    assert ok is False
    assert reason == "excluded-term"


def test_mine_example_corpus_merges_existing_examples(tmp_path, monkeypatch):
    examples_path = tmp_path / "examples.jsonl"
    report_path = tmp_path / "example-mining-report.json"
    examples_path.write_text(
        json.dumps(
            {
                "kind": "reviewed_manifest",
                "filename": "existing.pdf",
                "correct_label": "appeal",
                "primary_label": "appeal",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    fake_records = [
        {
            "id": 1,
            "external_id": "filesystem::/google1/Appeals/appeal-template.docx",
            "name": "appeal-template.docx",
            "path": "/google1/Appeals/appeal-template.docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "extension": "docx",
            "content_text": "Instructions for using the appeal template. Complaint and appeal form for denied claim.",
        },
            {
                "id": 2,
                "external_id": "filesystem::/google1/Finance/invoice-april.pdf",
                "name": "invoice-april.pdf",
                "path": "/google1/Finance/invoice-april.pdf",
                "mime_type": "application/pdf",
                "extension": "pdf",
                "content_text": "Vendor invoice with amount due, invoice number, statement date, billing statement, and payment terms.",
            },
    ]

    def fake_fetch(database_url: str, label: str, limit: int):
        if label in {"appeal", "appeal-template", "invoice", "billing-statement"}:
            return fake_records
        return []

    monkeypatch.setattr("apps.classifier.example_mining._fetch_candidate_records_for_label", fake_fetch)

    report = mine_example_corpus(
        database_url="postgresql://example/test",
        examples_path=examples_path,
        report_path=report_path,
    )

    lines = [json.loads(line) for line in examples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert report["existing_rows_preserved"] == 1
    assert report["mined_rows_added"] >= 1
    assert report["total_rows_written"] == len(lines)
    assert any(row.get("correct_label") in {"appeal", "appeal-template"} for row in lines)
