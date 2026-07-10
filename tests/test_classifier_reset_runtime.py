from pathlib import Path

from apps.classifier.reset_runtime import reset_generated_classifier_outputs


def test_reset_generated_classifier_outputs_removes_generated_vault_outputs_only(tmp_path: Path):
    vault_root = tmp_path / "vault"
    output_root = tmp_path / "output"

    generated_note = vault_root / "01 Classified" / "medical" / "note.md"
    review_note = vault_root / "02 Needs Review" / "review.md"
    attachment = vault_root / "90 Attachments" / "medical" / "note.pdf"
    classification_json = vault_root / "_system" / "classifications" / "note.json"
    extracted_markdown = vault_root / "_system" / "extracted-markdown" / "medical" / "note.extracted.md"
    index_file = vault_root / "Classification Index.md"
    inbox_note = vault_root / "00 Inbox" / "keep.md"
    template_file = vault_root / "_system" / "templates" / "keep.md"
    home_file = vault_root / "Home.md"
    readiness_file = output_root / "readiness-report.json"
    shadow_queue_file = output_root / "shadow-queue" / "job.json"
    shadow_comparison_file = output_root / "shadow-comparisons.jsonl"
    manifest_file = output_root / "manifest.jsonl"

    for path in [
        generated_note,
        review_note,
        attachment,
        classification_json,
        extracted_markdown,
        inbox_note,
        template_file,
        home_file,
        readiness_file,
        shadow_queue_file,
        shadow_comparison_file,
        manifest_file,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    index_file.write_text("# Index\n", encoding="utf-8")

    result = reset_generated_classifier_outputs(
        vault_root=vault_root,
        output_root=output_root,
    )

    assert result["ok"] is True
    assert result["removed"]["files"] >= 7
    assert not generated_note.exists()
    assert not review_note.exists()
    assert not attachment.exists()
    assert not classification_json.exists()
    assert not extracted_markdown.exists()
    assert not index_file.exists()
    assert not readiness_file.exists()
    assert not shadow_queue_file.exists()
    assert not shadow_comparison_file.exists()
    assert not manifest_file.exists()
    assert inbox_note.exists()
    assert template_file.exists()
    assert home_file.exists()
    assert (vault_root / "01 Classified").is_dir()
    assert (vault_root / "02 Needs Review").is_dir()
    assert (vault_root / "90 Attachments").is_dir()
    assert (vault_root / "_system" / "classifications").is_dir()
    assert (vault_root / "_system" / "extracted-markdown").is_dir()

