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


def test_create_document_vault_note_returns_existing_without_overwriting_user_content(
    monkeypatch,
    tmp_path: Path,
):
    vault_root = tmp_path / "document-vault"
    source_root = tmp_path / "mirrors"
    source_path = source_root / "google1" / "Appeal.docx"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    existing_note = vault_root / "01 Classified" / "appeal" / "Appeal - appeal.md"
    existing_note.parent.mkdir(parents=True, exist_ok=True)
    existing_note.write_text(
        "---\n"
        'type: "classified-document"\n'
        f'canonical_source_path: "{str(source_path.resolve()).replace("\\\\", "/")}"\n'
        'last_seen_filename: "Appeal.docx"\n'
        'primary_label: "appeal"\n'
        "---\n\n"
        "User-edited content that must remain intact.\n",
        encoding="utf-8",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("write path should not run when the note already exists")

    monkeypatch.setattr(
        "icloud_index_service.services.file_mutation_service.write_obsidian_note",
        fail_if_called,
    )

    result = create_document_vault_note(
        relative_folder="01 Classified/appeal",
        visible_title="Appeal",
        summary="Appeal summary.",
        canonical_source_path=str(source_path),
    )

    assert result["status"] == "existing"
    assert Path(result["note_path"]) == existing_note.resolve()
    assert existing_note.read_text(encoding="utf-8").endswith(
        "User-edited content that must remain intact.\n"
    )


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
