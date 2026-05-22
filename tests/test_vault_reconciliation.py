from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from icloud_index_service.models.base import Base
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "vault-reconciliation.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _add_file(
    session: Session,
    *,
    external_id: str,
    name: str,
    path: str,
    mime_type: str = "application/pdf",
    extension: str | None = "pdf",
) -> FileRecord:
    file_record = FileRecord(
        external_id=external_id,
        name=name,
        path=path,
        mime_type=mime_type,
        extension=extension,
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)
    return file_record


def _write_note(path: Path, *, canonical_source_path: str, canonical_source_hash: str, last_seen_filename: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                'type: classified-document',
                f'canonical_source_path: "{canonical_source_path}"',
                f'canonical_source_hash: "{canonical_source_hash}"',
                f'last_seen_filename: "{last_seen_filename}"',
                'attachment_mode: "copied-compatibility"',
                'compatibility_attachment_path: "[[90 Attachments/financial/Budget Draft.pdf]]"',
                "---",
                "",
                "# Sample",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_run_vault_reconciliation_once_repairs_note_when_unique_hash_match_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "Documents" / "Renamed Budget.pdf"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_bytes(b"budget-pdf")

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "financial" / "Budget Draft - financial - abc123def456.md"
    _write_note(
        note_path,
        canonical_source_path="/srv/cloud-vault/mirrors/icloud/Documents/Budget Draft.pdf",
        canonical_source_hash="6f693629f034268150d0c59ec406ba0157e82984145a6267379a91695a7728b5",
        last_seen_filename="Budget Draft.pdf",
    )

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    try:
        file_record = _add_file(
            session,
            external_id="file-1",
            name="Renamed Budget.pdf",
            path="/Documents/Renamed Budget.pdf",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path="/vault/01 Classified/financial/Budget Draft - financial - abc123def456.md",
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        session.expire_all()
        stored_state = session.scalar(select(ClassificationState).limit(1))
        updated_note = note_path.read_text(encoding="utf-8")
    finally:
        session.close()

    assert result["repaired"] == 1
    assert result["ambiguous"] == 0
    assert result["scanned"] == 1
    assert stored_state is not None
    assert stored_state.classifier_note_path == "/vault/01 Classified/financial/Budget Draft - financial - abc123def456.md"
    assert 'canonical_source_path: "/Documents/Renamed Budget.pdf"' not in updated_note
    assert f"canonical_source_path: {json.dumps(str(live_file))}" in updated_note
    assert 'last_seen_filename: "Renamed Budget.pdf"' in updated_note


def test_run_vault_reconciliation_once_leaves_note_untouched_when_hash_match_is_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    for file_name in ("Renamed Budget.pdf", "Budget Copy.pdf"):
        live_file = mirror_root / "Documents" / file_name
        live_file.parent.mkdir(parents=True, exist_ok=True)
        live_file.write_bytes(b"same-budget-pdf")

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "financial" / "Budget Draft - financial - abc123def456.md"
    original_note = (
        "---\n"
        'type: classified-document\n'
        'canonical_source_path: "/srv/cloud-vault/mirrors/icloud/Documents/Budget Draft.pdf"\n'
        'canonical_source_hash: "d04b43b6db50f9c2452542179f589d41a9c2cfae031be02043e5328bd0009214"\n'
        'last_seen_filename: "Budget Draft.pdf"\n'
        'attachment_mode: "copied-compatibility"\n'
        'compatibility_attachment_path: "[[90 Attachments/financial/Budget Draft.pdf]]"\n'
        "---\n\n# Sample\n"
    )
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(original_note, encoding="utf-8")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    try:
        file_record = _add_file(
            session,
            external_id="file-1",
            name="Renamed Budget.pdf",
            path="/Documents/Renamed Budget.pdf",
        )
        _add_file(
            session,
            external_id="file-2",
            name="Budget Copy.pdf",
            path="/Documents/Budget Copy.pdf",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path="/vault/01 Classified/financial/Budget Draft - financial - abc123def456.md",
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        updated_note = note_path.read_text(encoding="utf-8")
    finally:
        session.close()

    assert result["repaired"] == 0
    assert result["ambiguous"] == 1
    assert updated_note == original_note
