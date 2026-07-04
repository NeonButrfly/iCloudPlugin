from pathlib import Path

from icloud_index_service.services.file_mutation_service import create_document_vault_note


def test_create_document_vault_note_uses_categorizer_contract(monkeypatch, tmp_path: Path):
    vault_root = tmp_path / "document-vault"
    source_root = tmp_path / "mirrors"
    source_path = source_root / "google1" / "Appeal.docx"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    result = create_document_vault_note(
        relative_folder="01 Classified/appeal",
        visible_title="Appeal",
        summary="Appeal summary.",
        canonical_source_path=str(source_path),
    )

    note_text = Path(result["note_path"]).read_text(encoding="utf-8")
    assert "type: classified-document" in note_text
    assert "canonical_source_path:" in note_text
    assert "source_link:" in note_text
    assert "## Original File" in note_text


def test_create_document_vault_note_prefers_vault_local_attachment_link(monkeypatch, tmp_path: Path):
    vault_root = tmp_path / "document-vault"
    source_root = tmp_path / "mirrors"
    source_path = source_root / "google1" / "Appeal.docx"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    result = create_document_vault_note(
        relative_folder="01 Classified/appeal",
        visible_title="Appeal",
        summary="Appeal summary.",
        canonical_source_path=str(source_path),
        attach_originals=True,
    )

    note_text = Path(result["note_path"]).read_text(encoding="utf-8")
    assert "[[90 Attachments/" in note_text


def test_create_document_vault_note_requires_source_reference(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(tmp_path / "document-vault"))

    try:
        create_document_vault_note(
            relative_folder="01 Classified/appeal",
            visible_title="Appeal",
            summary="Appeal summary.",
        )
    except RuntimeError as exc:
        assert str(exc) == "Either file_id or canonical_source_path is required."
    else:
        raise AssertionError("Expected create_document_vault_note to reject missing source reference.")
