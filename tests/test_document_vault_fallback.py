from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from icloud_index_service.models.base import Base
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.classification_submission import ClassifierSubmissionNotReadyError
from icloud_index_service.services import file_mutation_service


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "document-vault-fallback.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _add_file(session: Session, *, name: str, path: str) -> FileRecord:
    file_record = FileRecord(
        external_id=f"ext-{name}",
        name=name,
        path=path,
        mime_type="application/pdf",
        extension="pdf",
        size_bytes=100,
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)
    return file_record


def test_fallback_note_creation_uses_file_id_and_classifier_result(monkeypatch, tmp_path: Path):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    vault_root = tmp_path / "document-vault"
    mirror_root = tmp_path / "mirrors"
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    file_record = _add_file(
        session,
        name="Nursing Progress Note.pdf",
        path="/google1/Medical/Nursing Progress Note.pdf",
    )

    def fake_classify(session_arg, *, file_record, force_reclassify=False, client=None):
        note_path = vault_root / "02 Needs Review" / "medical" / "Nursing Progress Note - medical.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(
            "---\n"
            'type: "classified-document"\n'
            'canonical_source_path: "/srv/cloud-vault/mirrors/google1/Medical/Nursing Progress Note.pdf"\n'
            'last_seen_filename: "Nursing Progress Note.pdf"\n'
            'primary_label: "medical"\n'
            "confidence: 0.62\n"
            "---\n\n# Nursing Progress Note\n",
            encoding="utf-8",
        )
        state = ClassificationState(
            file_id=file_record.id,
            submission_status="completed",
            classifier_note_path=str(note_path),
            primary_label="medical",
            confidence=0.62,
            summary="Clinical progress note.",
        )
        session_arg.add(state)
        session_arg.commit()
        return state, True

    monkeypatch.setattr(file_mutation_service, "classify_file_on_mcp_fallback", fake_classify)

    result = file_mutation_service.classify_file_and_create_document_vault_note_fallback(
        file_id=file_record.id,
        fallback_reason="chatgpt_payload_blocked",
        session=session,
    )

    assert result["status"] == "created"
    assert result["file_id"] == file_record.id
    assert result["used_classifier"] is True
    assert result["classifier_invocation"] == "mcp_fallback_only"
    assert result["primary_label"] == "medical"
    assert result["needs_review"] is True
    assert Path(str(result["note_path"])).exists()


def test_fallback_note_creation_returns_existing_without_invoking_classifier(monkeypatch, tmp_path: Path):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    vault_root = tmp_path / "document-vault"
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    file_record = _add_file(
        session,
        name="Appeal.pdf",
        path="/google1/Appeals/Appeal.pdf",
    )
    note_path = vault_root / "01 Classified" / "appeal" / "Appeal - appeal.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "---\n"
        'type: "classified-document"\n'
        'canonical_source_path: "/srv/cloud-vault/mirrors/google1/Appeals/Appeal.pdf"\n'
        'last_seen_filename: "Appeal.pdf"\n'
        'primary_label: "appeal"\n'
        "confidence: 0.91\n"
        "---\n\n# Appeal\n",
        encoding="utf-8",
    )
    session.add(
        ClassificationState(
            file_id=file_record.id,
            submission_status="completed",
            classifier_note_path=str(note_path),
            primary_label="appeal",
            confidence=0.91,
            summary="Appeal packet.",
        )
    )
    session.commit()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("classifier fallback should not run when an active note already exists")

    monkeypatch.setattr(file_mutation_service, "classify_file_on_mcp_fallback", fail_if_called)

    result = file_mutation_service.classify_file_and_create_document_vault_note_fallback(
        file_id=file_record.id,
        session=session,
    )

    assert result["status"] == "existing"
    assert result["used_classifier"] is False
    assert result["note_path"] == str(note_path.resolve())


def test_batch_fallback_handles_mixed_valid_and_invalid_file_ids(monkeypatch, tmp_path: Path):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    vault_root = tmp_path / "document-vault"
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    valid_file = _add_file(
        session,
        name="Receipt.pdf",
        path="/icloud/Receipts/Receipt.pdf",
    )

    def fake_single(*, file_id, **kwargs):
        if file_id != valid_file.id:
            return {
                "status": "failed",
                "file_id": file_id,
                "note_path": None,
                "change_set_id": None,
                "fallback_reason": "manual_fallback",
                "used_classifier": False,
                "classifier_invocation": "mcp_fallback_only",
                "classifier_status": "file-not-found",
                "primary_label": None,
                "confidence": None,
                "needs_review": False,
                "source_exists": False,
                "message": "missing",
            }
        return {
            "status": "created",
            "file_id": file_id,
            "note_path": str(vault_root / "01 Classified" / "receipt.md"),
            "change_set_id": "abc123",
            "fallback_reason": "manual_fallback",
            "used_classifier": True,
            "classifier_invocation": "mcp_fallback_only",
            "classifier_status": "completed",
            "primary_label": "receipt",
            "confidence": 0.95,
            "needs_review": False,
            "source_exists": True,
            "message": "ok",
        }

    monkeypatch.setattr(
        file_mutation_service,
        "classify_file_and_create_document_vault_note_fallback",
        fake_single,
    )

    result = file_mutation_service.batch_classify_files_and_create_document_vault_notes_fallback(
        file_ids=[valid_file.id, 999999],
        session=session,
    )

    assert result["count_created"] == 1
    assert result["count_failed"] == 1


def test_fallback_returns_unsupported_without_invoking_classifier(monkeypatch, tmp_path: Path):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    vault_root = tmp_path / "document-vault"
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    file_record = FileRecord(
        external_id="ext-config",
        name="settings.json",
        path="/icloud/Configs/settings.json",
        mime_type="application/json",
        extension="json",
        size_bytes=128,
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("classifier fallback should not run for unsupported extensions")

    monkeypatch.setattr(file_mutation_service, "classify_file_on_mcp_fallback", fail_if_called)

    result = file_mutation_service.classify_file_and_create_document_vault_note_fallback(
        file_id=file_record.id,
        session=session,
    )

    assert result["status"] == "unsupported"
    assert result["classifier_status"] == "unsupported"
    assert result["note_path"] is None
    assert "Unsupported classifier extension" in result["message"]


def test_batch_fallback_counts_unsupported_blocked_and_skipped(monkeypatch, tmp_path: Path):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    vault_root = tmp_path / "document-vault"
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    created_file = _add_file(session, name="Receipt.pdf", path="/icloud/Receipts/Receipt.pdf")
    existing_file = _add_file(session, name="Appeal.pdf", path="/icloud/Appeals/Appeal.pdf")
    unsupported_file = FileRecord(
        external_id="ext-json",
        name="payload.json",
        path="/icloud/Configs/payload.json",
        mime_type="application/json",
        extension="json",
        size_bytes=10,
    )
    blocked_file = _add_file(session, name="Plan.pdf", path="/icloud/Plans/Plan.pdf")
    session.add(unsupported_file)
    session.commit()
    session.refresh(unsupported_file)

    def fake_single(*, file_id, **kwargs):
        if file_id == created_file.id:
            return {"status": "created", "file_id": file_id, "note_path": "a.md", "classifier_status": "completed"}
        if file_id == existing_file.id:
            return {"status": "existing", "file_id": file_id, "note_path": "b.md", "classifier_status": "completed"}
        if file_id == unsupported_file.id:
            return {"status": "unsupported", "file_id": file_id, "note_path": None, "classifier_status": "unsupported"}
        if file_id == blocked_file.id:
            return {"status": "blocked", "file_id": file_id, "note_path": None, "classifier_status": "blocked"}
        raise ClassifierSubmissionNotReadyError("unexpected")

    monkeypatch.setattr(
        file_mutation_service,
        "classify_file_and_create_document_vault_note_fallback",
        fake_single,
    )

    result = file_mutation_service.batch_classify_files_and_create_document_vault_notes_fallback(
        file_ids=[created_file.id, existing_file.id, unsupported_file.id, blocked_file.id],
        skip_existing=True,
        session=session,
    )

    assert result["count_created"] == 1
    assert result["count_existing"] == 0
    assert result["count_skipped"] == 1
    assert result["count_unsupported"] == 1
    assert result["count_blocked"] == 1
