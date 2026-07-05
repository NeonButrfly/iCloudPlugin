from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from icloud_index_service.models.base import Base
from icloud_index_service.models.change_set import ChangeSet
from icloud_index_service.models.dedupe_group import DedupeGroup
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.dedupe_workflow_service import (
    analyze_duplicate_groups,
    apply_dedupe_group,
    continue_dedupe_job,
    get_dedupe_group,
    get_dedupe_job_status,
    list_dedupe_groups,
    start_dedupe_job,
)
from icloud_index_service.services.file_mutation_service import restore_change_set


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "dedupe-workflow.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _add_file(
    session: Session,
    *,
    namespace: str,
    relative_path: str,
    content: bytes,
    modified_at=None,
) -> FileRecord:
    file_record = FileRecord(
        external_id=f"{namespace}:{relative_path}",
        name=Path(relative_path).name,
        path=f"/{namespace}/{relative_path.replace(chr(92), '/')}",
        mime_type="application/pdf",
        extension=Path(relative_path).suffix.lstrip(".") or "pdf",
        size_bytes=len(content),
        modified_at=modified_at,
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)
    return file_record


def _write_live_file(tmp_path: Path, namespace: str, relative_path: str, content: bytes) -> Path:
    mirror_root = tmp_path / "mirrors"
    live_path = mirror_root / namespace / relative_path
    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_bytes(content)
    return live_path


def test_analyze_duplicate_groups_now_returns_job_id_without_scanning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        _add_file(session, namespace="icloud", relative_path="Docs/A.pdf", content=b"a")
        monkeypatch.setattr(
            "icloud_index_service.services.dedupe_workflow_service._compute_live_hash",
            lambda path: (_ for _ in ()).throw(AssertionError("legacy synchronous scan should not run")),
        )
        payload = analyze_duplicate_groups(session, namespaces=["icloud"], limit=1)
    finally:
        session.close()

    assert payload["deprecated"] is True
    assert payload["job_id"]


def test_start_and_continue_dedupe_job_exact_hash_is_chunked_and_repeatable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(tmp_path / "vault"))
    session = session_factory()
    try:
        _write_live_file(tmp_path, "icloud", "Docs/A.pdf", b"same")
        _write_live_file(tmp_path, "icloud", "Other/A-copy.pdf", b"same")
        first = _add_file(session, namespace="icloud", relative_path="Docs/A.pdf", content=b"same")
        second = _add_file(session, namespace="icloud", relative_path="Other/A-copy.pdf", content=b"same")
        start = start_dedupe_job(
            session,
            namespaces=["icloud"],
            strategy="exact_hash",
            chunk_size=1,
            max_groups=10,
            dry_run=True,
        )
        first_continue = continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=1, max_runtime_seconds=20)
        second_continue = continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=1, max_runtime_seconds=20)
        groups = list_dedupe_groups(session, job_id=str(start["job_id"]), limit=10)
        group_id = groups["groups"][0]["dedupe_group_id"]
        detail = get_dedupe_group(session, dedupe_group_id=group_id)
    finally:
        session.close()

    assert first_continue["status"] == "running"
    assert second_continue["status"] == "complete"
    assert second_continue["processed_count"] == 2
    assert groups["count"] == 1
    assert detail is not None
    assert detail["recommended_keep_file_id"] in {first.id, second.id}
    assert len(detail["members"]) == 2


def test_namespace_filter_is_applied_before_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        _write_live_file(tmp_path, "icloud", "Docs/A.pdf", b"same")
        _write_live_file(tmp_path, "icloud", "Docs/B.pdf", b"same")
        _write_live_file(tmp_path, "google1", "Docs/C.pdf", b"same")
        _write_live_file(tmp_path, "google1", "Docs/D.pdf", b"same")
        _add_file(session, namespace="icloud", relative_path="Docs/A.pdf", content=b"same")
        _add_file(session, namespace="icloud", relative_path="Docs/B.pdf", content=b"same")
        _add_file(session, namespace="google1", relative_path="Docs/C.pdf", content=b"same")
        _add_file(session, namespace="google1", relative_path="Docs/D.pdf", content=b"same")
        start = start_dedupe_job(session, namespaces=["google1"], strategy="exact_hash", chunk_size=10)
        continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=10, max_runtime_seconds=20)
        payload = list_dedupe_groups(session, job_id=str(start["job_id"]), limit=10)
    finally:
        session.close()

    assert payload["count"] == 1


def test_max_groups_stops_early(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        for name, content in (
            ("Docs/A.pdf", b"same-1"),
            ("Docs/B.pdf", b"same-1"),
            ("Docs/C.pdf", b"same-2"),
            ("Docs/D.pdf", b"same-2"),
        ):
            _write_live_file(tmp_path, "icloud", name, content)
            _add_file(session, namespace="icloud", relative_path=name, content=content)
        start = start_dedupe_job(session, namespaces=["icloud"], strategy="exact_hash", chunk_size=10, max_groups=1)
        payload = continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=10, max_runtime_seconds=20)
    finally:
        session.close()

    assert payload["status"] == "complete"
    assert payload["groups_found"] == 1


def test_normalized_name_size_strategy_groups_without_live_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        _write_live_file(tmp_path, "icloud", "Docs/Appeal Final.pdf", b"one")
        _write_live_file(tmp_path, "icloud", "Docs/appeal-final.pdf", b"two")
        _add_file(session, namespace="icloud", relative_path="Docs/Appeal Final.pdf", content=b"one")
        _add_file(session, namespace="icloud", relative_path="Docs/appeal-final.pdf", content=b"two")
        start = start_dedupe_job(session, namespaces=["icloud"], strategy="normalized_name_size", chunk_size=10)
        continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=10, max_runtime_seconds=20)
        payload = list_dedupe_groups(session, job_id=str(start["job_id"]), limit=10, strategy="normalized_name_size")
    finally:
        session.close()

    assert payload["count"] == 1
    assert payload["groups"][0]["confidence"] < 0.9


def test_content_hash_strategy_uses_extracted_content_in_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        for relative_path in ("Docs/A.txt", "Docs/B.txt", "Docs/C.txt"):
            _write_live_file(tmp_path, "icloud", relative_path, relative_path.encode("utf-8"))
            record = _add_file(session, namespace="icloud", relative_path=relative_path, content=relative_path.encode("utf-8"))
            session.add(
                ExtractedContent(
                    file_id=record.id,
                    content_text="same-body" if relative_path != "Docs/C.txt" else "different",
                    content_hash="shared-hash" if relative_path != "Docs/C.txt" else "other-hash",
                )
            )
        session.commit()
        start = start_dedupe_job(session, namespaces=["icloud"], strategy="content_hash", chunk_size=1)
        first = continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=1, max_runtime_seconds=20)
        second = continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=1, max_runtime_seconds=20)
        third = continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=1, max_runtime_seconds=20)
        payload = list_dedupe_groups(session, job_id=str(start["job_id"]), limit=10, strategy="content_hash")
    finally:
        session.close()

    assert first["processed_count"] == 1
    assert second["processed_count"] == 2
    assert third["status"] == "complete"
    assert payload["count"] == 1


def test_large_duplicate_group_totals_are_preserved_for_multi_gb_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        _write_live_file(tmp_path, "icloud", "Docs/A.iso", b"same")
        _write_live_file(tmp_path, "icloud", "Docs/B.iso", b"same")
        first = _add_file(session, namespace="icloud", relative_path="Docs/A.iso", content=b"same")
        second = _add_file(session, namespace="icloud", relative_path="Docs/B.iso", content=b"same")
        first.size_bytes = 3_274_047_984
        second.size_bytes = 3_274_047_984
        session.commit()
        start = start_dedupe_job(session, namespaces=["icloud"], strategy="exact_hash", chunk_size=10)
        payload = continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=10, max_runtime_seconds=20)
        group = session.scalar(select(DedupeGroup).where(DedupeGroup.dedupe_job_id.is_not(None)))
    finally:
        session.close()

    assert payload["status"] == "complete"
    assert group is not None
    assert group.total_size_bytes == 6_548_095_968


def test_apply_dedupe_group_dry_run_moves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        _write_live_file(tmp_path, "icloud", "Docs/A.pdf", b"same")
        _write_live_file(tmp_path, "icloud", "Docs/B.pdf", b"same")
        first = _add_file(session, namespace="icloud", relative_path="Docs/A.pdf", content=b"same")
        second = _add_file(session, namespace="icloud", relative_path="Docs/B.pdf", content=b"same")
        start = start_dedupe_job(session, namespaces=["icloud"], strategy="exact_hash", chunk_size=10)
        continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=10, max_runtime_seconds=20)
        group_id = list_dedupe_groups(session, job_id=str(start["job_id"]), limit=10)["groups"][0]["dedupe_group_id"]
        payload = apply_dedupe_group(
            session,
            dedupe_group_id=group_id,
            keep_file_id=first.id,
            move_to_backup_file_ids=[second.id],
            dry_run=True,
        )
    finally:
        session.close()

    assert payload["status"] == "dry_run"
    assert (tmp_path / "mirrors" / "icloud" / "Docs" / "B.pdf").exists()


def test_apply_dedupe_group_rejects_invalid_keep_delete_combo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        _write_live_file(tmp_path, "icloud", "Docs/A.pdf", b"same")
        _write_live_file(tmp_path, "icloud", "Docs/B.pdf", b"same")
        first = _add_file(session, namespace="icloud", relative_path="Docs/A.pdf", content=b"same")
        _add_file(session, namespace="icloud", relative_path="Docs/B.pdf", content=b"same")
        start = start_dedupe_job(session, namespaces=["icloud"], strategy="exact_hash", chunk_size=10)
        continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=10, max_runtime_seconds=20)
        group_id = list_dedupe_groups(session, job_id=str(start["job_id"]), limit=10)["groups"][0]["dedupe_group_id"]
        with pytest.raises(Exception, match="keep_file_id cannot also be moved"):
            apply_dedupe_group(
                session,
                dedupe_group_id=group_id,
                keep_file_id=first.id,
                move_to_backup_file_ids=[first.id],
                dry_run=True,
            )
    finally:
        session.close()


def test_apply_dedupe_group_moves_duplicates_and_creates_reversible_change_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(tmp_path / "vault"))
    session = session_factory()
    try:
        kept_path = _write_live_file(tmp_path, "icloud", "Docs/A.pdf", b"same")
        moved_path = _write_live_file(tmp_path, "google1", "Docs/B.pdf", b"same")
        first = _add_file(session, namespace="icloud", relative_path="Docs/A.pdf", content=b"same")
        second = _add_file(session, namespace="google1", relative_path="Docs/B.pdf", content=b"same")
        start = start_dedupe_job(session, namespaces=["icloud", "google1"], strategy="exact_hash", chunk_size=10)
        continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=10, max_runtime_seconds=20)
        group_id = list_dedupe_groups(session, job_id=str(start["job_id"]), limit=10)["groups"][0]["dedupe_group_id"]
        payload = apply_dedupe_group(
            session,
            dedupe_group_id=group_id,
            keep_file_id=first.id,
            move_to_backup_file_ids=[second.id],
            dry_run=False,
        )
        change_set = session.scalar(select(ChangeSet).where(ChangeSet.change_set_id == payload["change_set_id"]))
        restored = restore_change_set(change_set_id=str(payload["change_set_id"]), actor="pytest", session=session)
    finally:
        session.close()

    assert payload["status"] == "moved"
    assert kept_path.exists()
    assert moved_path.exists()
    assert change_set is not None
    assert restored["status"] == "restored"


def test_get_dedupe_job_status_returns_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_factory = _build_session_factory(tmp_path)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(tmp_path / "mirrors"))
    session = session_factory()
    try:
        _write_live_file(tmp_path, "icloud", "Docs/A.pdf", b"same")
        _write_live_file(tmp_path, "icloud", "Docs/B.pdf", b"same")
        _add_file(session, namespace="icloud", relative_path="Docs/A.pdf", content=b"same")
        _add_file(session, namespace="icloud", relative_path="Docs/B.pdf", content=b"same")
        start = start_dedupe_job(session, namespaces=["icloud"], strategy="exact_hash", chunk_size=1)
        continue_dedupe_job(session, job_id=str(start["job_id"]), chunk_size=1, max_runtime_seconds=20)
        payload = get_dedupe_job_status(session, job_id=str(start["job_id"]))
    finally:
        session.close()

    assert payload["job_id"] == start["job_id"]
    assert payload["processed_count"] == 1
