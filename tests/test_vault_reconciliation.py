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


def test_run_vault_reconciliation_once_updates_state_to_matching_current_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "icloud" / "project kay memory.pdf"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_bytes(b"project-kay-memory")

    vault_root = tmp_path / "vault"
    current_note_path = vault_root / "02 Needs Review" / "project kay memory - financial.md"
    _write_note(
        current_note_path,
        canonical_source_path=str(live_file),
        canonical_source_hash="2613fcd123f94ff13f061e00f1f34df85ba978db8d6a8bc6ac3c44f55e0b6910",
        last_seen_filename="project kay memory.pdf",
    )

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    stale_note_reference = "/vault/02 Needs Review/project kay memory - medical (2).md"
    current_note_reference = "/vault/02 Needs Review/project kay memory - financial.md"

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    try:
        file_record = _add_file(
            session,
            external_id="file-1",
            name="project kay memory.pdf",
            path="/icloud/project kay memory.pdf",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path=stale_note_reference,
                classifier_manifest_record=json.dumps(
                    {
                        "note_path": stale_note_reference,
                        "canonical_source_path": str(live_file),
                        "canonical_source_hash": "2613fcd123f94ff13f061e00f1f34df85ba978db8d6a8bc6ac3c44f55e0b6910",
                        "last_seen_filename": "project kay memory.pdf",
                    }
                ),
                response_payload_json=json.dumps(
                    {
                        "record": {
                            "note_path": stale_note_reference,
                            "canonical_source_path": str(live_file),
                            "canonical_source_hash": "2613fcd123f94ff13f061e00f1f34df85ba978db8d6a8bc6ac3c44f55e0b6910",
                            "last_seen_filename": "project kay memory.pdf",
                        }
                    }
                ),
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        session.expire_all()
        stored_state = session.scalar(select(ClassificationState).limit(1))
    finally:
        session.close()

    assert result["repaired"] == 1
    assert result["scanned"] == 1
    assert stored_state is not None
    assert stored_state.classifier_note_path == current_note_reference
    assert json.loads(stored_state.classifier_manifest_record)["note_path"] == current_note_reference
    assert json.loads(stored_state.response_payload_json)["record"]["note_path"] == current_note_reference


def test_run_vault_reconciliation_once_normalizes_legacy_hash_note_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "icloud" / "Budget Draft.pdf"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_bytes(b"budget-pdf")

    vault_root = tmp_path / "vault"
    legacy_note_path = vault_root / "01 Classified" / "financial" / "Budget Draft - financial - abc123def456.md"
    _write_note(
        legacy_note_path,
        canonical_source_path=str(live_file),
        canonical_source_hash="6f693629f034268150d0c59ec406ba0157e82984145a6267379a91695a7728b5",
        last_seen_filename="Budget Draft.pdf",
    )
    legacy_note_path.write_text(
        legacy_note_path.read_text(encoding="utf-8").replace(
            'attachment_mode: "copied-compatibility"\n',
            'primary_label: "financial"\nattachment_mode: "copied-compatibility"\n',
        ),
        encoding="utf-8",
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
            name="Budget Draft.pdf",
            path="/icloud/Budget Draft.pdf",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path="/vault/01 Classified/financial/Budget Draft - financial - abc123def456.md",
                classifier_manifest_record=json.dumps(
                    {
                        "note_path": "/vault/01 Classified/financial/Budget Draft - financial - abc123def456.md",
                        "canonical_source_path": str(live_file),
                        "canonical_source_hash": "6f693629f034268150d0c59ec406ba0157e82984145a6267379a91695a7728b5",
                        "last_seen_filename": "Budget Draft.pdf",
                    }
                ),
                response_payload_json=json.dumps(
                    {
                        "record": {
                            "note_path": "/vault/01 Classified/financial/Budget Draft - financial - abc123def456.md",
                            "canonical_source_path": str(live_file),
                            "canonical_source_hash": "6f693629f034268150d0c59ec406ba0157e82984145a6267379a91695a7728b5",
                            "last_seen_filename": "Budget Draft.pdf",
                        }
                    }
                ),
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        session.expire_all()
        stored_state = session.scalar(select(ClassificationState).limit(1))
    finally:
        session.close()

    clean_note_path = vault_root / "01 Classified" / "financial" / "Budget Draft - financial.md"

    assert result["repaired"] == 1
    assert not legacy_note_path.exists()
    assert clean_note_path.exists()
    assert stored_state is not None
    assert stored_state.classifier_note_path == "/vault/01 Classified/financial/Budget Draft - financial.md"
    assert json.loads(stored_state.classifier_manifest_record)["note_path"] == "/vault/01 Classified/financial/Budget Draft - financial.md"
    assert json.loads(stored_state.response_payload_json)["record"]["note_path"] == "/vault/01 Classified/financial/Budget Draft - financial.md"


def test_run_vault_reconciliation_once_prefers_unsuffixed_matching_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "icloud" / "uber_f1099k_2025.pdf"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_bytes(b"uber-tax-document")

    vault_root = tmp_path / "vault"
    canonical_source_hash = "8da613b5d5261de8cb6445f8007a31b9e8a99c0fbd5316db4257c7cb66395c10"
    last_seen_filename = "uber_f1099k_2025.pdf"
    unsuffixed_note_path = vault_root / "01 Classified" / "financial" / "uber_f1099k_2025 - financial.md"
    suffixed_note_path = vault_root / "01 Classified" / "financial" / "uber_f1099k_2025 - financial (2).md"
    _write_note(
        unsuffixed_note_path,
        canonical_source_path=str(live_file),
        canonical_source_hash=canonical_source_hash,
        last_seen_filename=last_seen_filename,
    )
    _write_note(
        suffixed_note_path,
        canonical_source_path=str(live_file),
        canonical_source_hash=canonical_source_hash,
        last_seen_filename=last_seen_filename,
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
            name=last_seen_filename,
            path="/icloud/uber_f1099k_2025.pdf",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path="/vault/01 Classified/financial/uber_f1099k_2025 - financial (2).md",
                classifier_manifest_record=json.dumps(
                    {
                        "note_path": "/vault/01 Classified/financial/uber_f1099k_2025 - financial (2).md",
                        "canonical_source_path": str(live_file),
                        "canonical_source_hash": canonical_source_hash,
                        "last_seen_filename": last_seen_filename,
                    }
                ),
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        session.expire_all()
        stored_state = session.scalar(select(ClassificationState).limit(1))
    finally:
        session.close()

    assert result["repaired"] == 1
    assert stored_state is not None
    assert (
        stored_state.classifier_note_path
        == "/vault/01 Classified/financial/uber_f1099k_2025 - financial.md"
    )


def test_run_vault_reconciliation_once_repairs_stale_source_link_fields_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import (
        _build_canonical_source_link,
        run_vault_reconciliation_once,
    )

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "icloud" / "Scanned" / "botox.pdf"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_bytes(b"botox-pdf")

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "medical" / "botox - medical.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: classified-document',
                f'canonical_source_path: {json.dumps(str(live_file))}',
                'canonical_source_hash: "abc123"',
                'last_seen_filename: "botox.pdf"',
                'attachment_mode: "canonical-source-link"',
                'compatibility_attachment_path: ""',
                'source_link: "[botox.pdf](file://192.168.50.86/cloud-vault/mirrors/icloud/Scanned/botox.pdf)"',
                'attachment: "[botox.pdf](file://192.168.50.86/cloud-vault/mirrors/icloud/Scanned/botox.pdf)"',
                "---",
                "",
                "# botox.pdf",
                "",
                "## Original File",
                "",
                "[botox.pdf](file://192.168.50.86/cloud-vault/mirrors/icloud/Scanned/botox.pdf)",
                "",
                "## Extracted Markdown File",
                "",
                "_none_",
            ]
        )
        + "\n",
        encoding="utf-8",
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
            name="botox.pdf",
            path="/icloud/Scanned/botox.pdf",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path="/vault/01 Classified/medical/botox - medical.md",
                classifier_manifest_record=json.dumps(
                    {
                        "note_path": "/vault/01 Classified/medical/botox - medical.md",
                        "canonical_source_path": str(live_file),
                        "canonical_source_hash": "abc123",
                        "last_seen_filename": "botox.pdf",
                        "attachment_mode": "canonical-source-link",
                        "compatibility_attachment_path": "",
                        "source_link": "[botox.pdf](file://192.168.50.86/cloud-vault/mirrors/icloud/Scanned/botox.pdf)",
                    }
                ),
                response_payload_json=json.dumps(
                    {
                        "record": {
                            "note_path": "/vault/01 Classified/medical/botox - medical.md",
                            "canonical_source_path": str(live_file),
                            "canonical_source_hash": "abc123",
                            "last_seen_filename": "botox.pdf",
                            "attachment_mode": "canonical-source-link",
                            "compatibility_attachment_path": "",
                            "source_link": "[botox.pdf](file://192.168.50.86/cloud-vault/mirrors/icloud/Scanned/botox.pdf)",
                        }
                    }
                ),
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        session.expire_all()
        stored_state = session.scalar(select(ClassificationState).limit(1))
        updated_note = note_path.read_text(encoding="utf-8")
    finally:
        session.close()

    expected_link = _build_canonical_source_link(str(live_file), "botox.pdf")
    assert result["repaired"] == 1
    assert result["scanned"] == 1
    assert expected_link in updated_note
    assert f'source_link: {json.dumps(expected_link)}' in updated_note
    assert f'attachment: {json.dumps(expected_link)}' in updated_note
    assert stored_state is not None
    assert json.loads(stored_state.classifier_manifest_record)["source_link"] == expected_link
    assert json.loads(stored_state.response_payload_json)["record"]["source_link"] == expected_link


def test_run_vault_reconciliation_once_backfills_missing_classifier_context_into_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "icloud" / "Scanned" / "receipt.pdf"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_bytes(b"receipt-pdf")

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "receipt" / "receipt - receipt.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: classified-document',
                'primary_label: "receipt"',
                'canonical_source_path: ""',
                'canonical_source_hash: "abc123"',
                'last_seen_filename: "receipt.pdf"',
                'attachment_mode: "canonical-source-link"',
                'compatibility_attachment_path: ""',
                'source_link: ""',
                "---",
                "",
                "# receipt.pdf",
            ]
        )
        + "\n",
        encoding="utf-8",
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
            name="receipt.pdf",
            path="/icloud/Scanned/receipt.pdf",
        )
        note_reference = "/vault/01 Classified/receipt/receipt - receipt.md"
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path=note_reference,
                classifier_manifest_record=json.dumps(
                    {
                        "note_path": note_reference,
                        "canonical_source_path": str(live_file),
                        "canonical_source_hash": "abc123",
                        "last_seen_filename": "receipt.pdf",
                        "timing": {"parser": "pdf-ocr-tesseract"},
                        "hybrid": {
                            "decision": {
                                "live_source": "manual-correction-override",
                            }
                        },
                    }
                ),
                response_payload_json=json.dumps(
                    {
                        "record": {
                            "note_path": note_reference,
                            "canonical_source_path": str(live_file),
                            "canonical_source_hash": "abc123",
                            "last_seen_filename": "receipt.pdf",
                            "timing": {"parser": "pdf-ocr-tesseract"},
                            "hybrid": {
                                "decision": {
                                    "live_source": "manual-correction-override",
                                }
                            },
                        }
                    }
                ),
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        updated_note = note_path.read_text(encoding="utf-8")
    finally:
        session.close()

    assert result["repaired"] == 1
    assert 'canonical_source_path: ""' not in updated_note
    assert f'canonical_source_path: {json.dumps(str(live_file))}' in updated_note
    assert 'source_parser: "pdf-ocr-tesseract"' in updated_note
    assert 'heuristic_primary_hint: "unknown"' in updated_note
    assert 'hybrid_live_source: "manual-correction-override"' in updated_note


def test_run_vault_reconciliation_once_derives_missing_classifier_context_from_source_when_state_payload_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "google1" / "Docs" / "Appeal.txt"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_text(
        "\n".join(
            [
                "Appeal Request",
                "Please review the denied insurance coverage decision.",
                "Supporting policy and claim references are attached.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "insurance" / "Appeal - insurance.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "insurance"',
                f'canonical_source_path: {json.dumps(str(live_file))}',
                'canonical_source_hash: "abc123"',
                'last_seen_filename: "Appeal.txt"',
                'attachment_mode: "canonical-source-link"',
                'compatibility_attachment_path: ""',
                "---",
                "",
                "# Appeal.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
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
            name="Appeal.txt",
            path="/google1/Docs/Appeal.txt",
            mime_type="text/plain",
            extension="txt",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path="/vault/01 Classified/insurance/Appeal - insurance.md",
                classifier_manifest_record="",
                response_payload_json="",
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        updated_note = note_path.read_text(encoding="utf-8")
    finally:
        session.close()

    assert result["repaired"] == 1
    assert 'source_parser: "plain-text"' in updated_note
    assert 'heuristic_primary_hint: "unknown"' in updated_note
    assert 'hybrid_live_source: ""' in updated_note


def test_run_vault_reconciliation_once_preserves_existing_note_context_when_deriving_missing_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from icloud_index_service.services.vault_reconciliation import run_vault_reconciliation_once

    mirror_root = tmp_path / "mirror"
    live_file = mirror_root / "icloud" / "Scanned" / "notes.txt"
    live_file.parent.mkdir(parents=True, exist_ok=True)
    live_file.write_text(
        "\n".join(
            [
                "Technical Notes",
                "Deployment settings",
                "Terminal output",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "technical" / "notes - technical.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "technical"',
                f'canonical_source_path: {json.dumps(str(live_file))}',
                'canonical_source_hash: "abc123"',
                'last_seen_filename: "notes.txt"',
                'attachment_mode: "canonical-source-link"',
                'compatibility_attachment_path: ""',
                'source_parser: "manual-parser"',
                "---",
                "",
                "# notes.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
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
            name="notes.txt",
            path="/icloud/Scanned/notes.txt",
            mime_type="text/plain",
            extension="txt",
        )
        session.add(
            ClassificationState(
                file_id=file_record.id,
                submission_status="completed",
                classifier_note_path="/vault/01 Classified/technical/notes - technical.md",
                classifier_manifest_record="",
                response_payload_json="",
            )
        )
        session.commit()

        result = run_vault_reconciliation_once(session, limit=10)
        updated_note = note_path.read_text(encoding="utf-8")
    finally:
        session.close()

    assert result["repaired"] == 1
    assert 'source_parser: "manual-parser"' in updated_note
    assert 'heuristic_primary_hint: "unknown"' in updated_note


def test_sync_manual_note_feedback_exports_changed_manual_notes(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    note_path = vault_root / "Projects" / "Kay Appeal.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'primary_label: "appeal"',
                'canonical_source_path: "/srv/cloud-vault/mirrors/icloud/Scanned/appeal.pdf"',
                "---",
                "",
                "# Kay Appeal",
                "",
                "Appeal planning notes.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"

    first_result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["appeal", "markdown-note"],
    )
    second_result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["appeal", "markdown-note"],
    )

    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert first_result == {"scanned": 1, "exported": 1, "unchanged": 0}
    assert second_result == {"scanned": 1, "exported": 0, "unchanged": 1}
    assert rows[0]["correct_label"] == "appeal"
    assert rows[0]["source_path"] == "/srv/cloud-vault/mirrors/icloud/Scanned/appeal.pdf"
    assert rows[0]["note"] == "manual-obsidian-note:Projects/Kay Appeal.md"


def test_sync_manual_note_feedback_uses_folder_as_weak_label_when_mapped(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    note_path = vault_root / "Receipts" / "Lowe's trip.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# Lowe's trip\n\nStore visit notes.\n", encoding="utf-8")

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"
    folder_map_path = tmp_path / "vault-folder-labels.json"
    folder_map_path.write_text(
        json.dumps({"receipts": {"primary_label": "receipt"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["receipt", "markdown-note"],
        folder_label_map_path=folder_map_path,
    )

    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"scanned": 1, "exported": 1, "unchanged": 0}
    assert rows[0]["correct_label"] == "receipt"
    assert rows[0]["review_status"] == "manual-folder-weak-label"
    assert rows[0]["feedback_strength"] == "weak"
    assert rows[0]["folder_match_source"] == "explicit-folder-map"


def test_sync_manual_note_feedback_exports_generated_note_move_as_correction(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "insurance" / "botox - medical.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "medical"',
                'secondary_labels: []',
                'recommended_action: "retain"',
                'source_parser: "pdf-ocr-tesseract"',
                'heuristic_primary_hint: "unknown"',
                'canonical_source_path: "/srv/cloud-vault/mirrors/icloud/Scanned/botox.pdf"',
                "---",
                "",
                "# botox.pdf",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["medical", "insurance", "markdown-note"],
    )

    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"scanned": 1, "exported": 1, "unchanged": 0}
    assert rows[0]["source_path"] == "/srv/cloud-vault/mirrors/icloud/Scanned/botox.pdf"
    assert rows[0]["correct_label"] == "insurance"
    assert rows[0]["old_label"] == "medical"
    assert rows[0]["review_status"] == "manual-note-move"
    assert rows[0]["feedback_strength"] == "strong"
    assert rows[0]["parser"] == "pdf-ocr-tesseract"
    assert rows[0]["heuristic_primary"] == "unknown"


def test_sync_manual_note_feedback_exports_generated_note_secondary_label_move(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "medical" / "appeals" / "botox - medical.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "medical"',
                'secondary_labels: []',
                'recommended_action: "retain"',
                'source_parser: "pdf-ocr-tesseract"',
                'heuristic_primary_hint: "unknown"',
                'canonical_source_path: "/srv/cloud-vault/mirrors/icloud/Scanned/botox.pdf"',
                "---",
                "",
                "# botox.pdf",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"
    folder_map_path = tmp_path / "vault-folder-labels.json"
    folder_map_path.write_text(
        json.dumps(
            {
                "medical/appeals": {
                    "primary_label": "medical",
                    "secondary_labels": ["appeal"],
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["medical", "appeal", "markdown-note"],
        folder_label_map_path=folder_map_path,
    )

    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"scanned": 1, "exported": 1, "unchanged": 0}
    assert rows[0]["correct_label"] == "medical"
    assert rows[0]["old_label"] == "medical"
    assert rows[0]["secondary_labels"] == ["appeal"]
    assert rows[0]["old_secondary_labels"] == []


def test_sync_manual_note_feedback_derives_missing_generated_note_context_from_source(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    source_path = tmp_path / "sources" / "agreement.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "\n".join(
            [
                "Service Agreement",
                "Scope of services",
                "Term and termination",
                "Confidentiality",
                "Payment terms",
                "Limitation of liability",
                "Governing law",
                "Parties",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    note_path = vault_root / "01 Classified" / "legal" / "agreement - legal.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "financial"',
                'secondary_labels: []',
                'recommended_action: "retain"',
                f'canonical_source_path: "{source_path.as_posix()}"',
                "---",
                "",
                "# agreement.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["legal", "financial", "markdown-note"],
    )

    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"scanned": 1, "exported": 1, "unchanged": 0}
    assert rows[0]["correct_label"] == "legal"
    assert rows[0]["old_label"] == "financial"
    assert rows[0]["parser"] == "plain-text"
    assert rows[0]["heuristic_primary"] == "legal"


@pytest.mark.parametrize(
    "canonical_source_path",
    [
        "/srv/cloud-vault/mirrors/google1/Docs/Appeal.txt",
        "/mnt/cloud-vault/mirrors/google1/Docs/Appeal.txt",
    ],
)
def test_sync_manual_note_feedback_translates_canonical_mirror_path_into_classifier_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    canonical_source_path: str,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    source_root = tmp_path / "source"
    source_path = source_root / "google1" / "Docs" / "Appeal.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "\n".join(
            [
                "Appeal Request",
                "This appeal concerns denied coverage and requested review.",
                "Insurance carrier response attached.",
                "Please reconsider the original determination.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    note_path = vault_root / "01 Classified" / "appeal" / "Appeal - insurance.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "insurance"',
                'secondary_labels: []',
                'recommended_action: "retain"',
                f'canonical_source_path: "{canonical_source_path}"',
                "---",
                "",
                "# Appeal.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("CLASSIFIER_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", "/srv/cloud-vault/mirrors")

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["appeal", "insurance", "markdown-note"],
    )

    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"scanned": 1, "exported": 1, "unchanged": 0}
    assert rows[0]["correct_label"] == "appeal"
    assert rows[0]["old_label"] == "insurance"
    assert rows[0]["parser"] == "plain-text"
    assert rows[0]["heuristic_primary"] == "unknown"


def test_sync_manual_note_feedback_reexports_when_legacy_state_fingerprint_lacks_context_fields(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    source_path = tmp_path / "sources" / "agreement.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "\n".join(
            [
                "Service Agreement",
                "Scope of services",
                "Term and termination",
                "Confidentiality",
                "Payment terms",
                "Limitation of liability",
                "Governing law",
                "Parties",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    note_path = vault_root / "01 Classified" / "legal" / "agreement - legal.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "financial"',
                'secondary_labels: []',
                'recommended_action: "retain"',
                f'canonical_source_path: "{source_path.as_posix()}"',
                "---",
                "",
                "# agreement.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"
    legacy_fingerprint = (
        f"{note_path.resolve().as_posix()}:"
        f"{note_path.stat().st_mtime_ns}:"
        f"{note_path.stat().st_size}:"
        "legal:"
        "manual-note-move"
    )
    state_path.write_text(
        json.dumps(
            {
                f"generated:{source_path.as_posix()}": legacy_fingerprint,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["legal", "financial", "markdown-note"],
    )

    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"scanned": 1, "exported": 1, "unchanged": 0}
    assert rows[0]["parser"] == "plain-text"
    assert rows[0]["heuristic_primary"] == "legal"


def test_sync_manual_note_feedback_skips_generated_note_when_path_still_matches_default(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    note_path = vault_root / "01 Classified" / "medical" / "botox - medical.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "medical"',
                'secondary_labels: []',
                'recommended_action: "retain"',
                'canonical_source_path: "/srv/cloud-vault/mirrors/icloud/Scanned/botox.pdf"',
                "---",
                "",
                "# botox.pdf",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["medical", "insurance", "markdown-note"],
    )

    assert result == {"scanned": 1, "exported": 0, "unchanged": 1}
    assert not feedback_path.exists()


def test_sync_manual_note_feedback_skips_generated_note_move_when_label_is_unchanged(
    tmp_path: Path,
):
    from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback

    vault_root = tmp_path / "vault"
    note_path = vault_root / "02 Needs Review" / "financial" / "receipt - financial.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                'primary_label: "financial"',
                'secondary_labels: []',
                'recommended_action: "keep"',
                'canonical_source_path: "/srv/cloud-vault/mirrors/icloud/Scanned/receipt.pdf"',
                "---",
                "",
                "# receipt.pdf",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    feedback_path = tmp_path / "manual-note-feedback.jsonl"
    state_path = tmp_path / "manual-note-sync-state.json"

    result = sync_manual_note_feedback(
        vault_root,
        feedback_path=feedback_path,
        state_path=state_path,
        known_labels=["financial", "receipt", "markdown-note"],
    )

    assert result == {"scanned": 1, "exported": 0, "unchanged": 1}
    assert not feedback_path.exists()
