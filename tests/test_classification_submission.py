from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from icloud_index_service.models.base import Base
from icloud_index_service.models.classification_job import ClassificationJob
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.classification_submission import (
    CLASSIFICATION_STATUS_COMPLETED,
    CLASSIFICATION_STATUS_FAILED,
    CLASSIFICATION_STATUS_QUEUED,
    CLASSIFICATION_STATUS_RUNNING,
    ClassifierApiClient,
    ClassifierSubmissionNotReadyError,
    DEFAULT_CLASSIFICATION_MAX_ATTEMPTS,
    DEFAULT_CLASSIFICATION_SUBMISSION_CONCURRENCY,
    compute_source_fingerprint,
    enqueue_classification_backfill,
    get_classification_submission_concurrency,
    run_next_classification_job,
)
from icloud_index_service.classification_worker import run_classification_worker_once


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "classification.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class FakeClassifierClient:
    def __init__(self, response: dict[str, object] | None = None, *, error: Exception | None = None) -> None:
        self._response = response or {
            "ok": True,
            "record": {
                "primary_label": "Finance",
                "summary": "Quarterly budget draft",
                "confidence": 0.93,
                "reasoning": "Contains budget planning details.",
                "note_path": "01 Classified/finance/Budget.md",
            },
        }
        self._error = error
        self.calls: list[dict[str, object]] = []

    def submit_file(
        self,
        *,
        file_path: Path,
        file_name: str,
        canonical_source_path: str | None = None,
        canonical_source_hash: str | None = None,
        last_seen_filename: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "file_path": file_path,
                "file_name": file_name,
                "canonical_source_path": canonical_source_path,
                "canonical_source_hash": canonical_source_hash,
                "last_seen_filename": last_seen_filename,
            }
        )
        if self._error is not None:
            raise self._error
        return self._response


def _add_file(
    session: Session,
    *,
    external_id: str,
    name: str,
    path: str,
    mime_type: str,
    extension: str | None,
    size_bytes: int | None = None,
) -> FileRecord:
    file_record = FileRecord(
        external_id=external_id,
        name=name,
        path=path,
        mime_type=mime_type,
        extension=extension,
        size_bytes=size_bytes,
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)
    return file_record


def test_enqueue_classification_backfill_prioritizes_documents_then_images_for_supported_types(
    tmp_path: Path,
):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()

    try:
        image_file = _add_file(
            session,
            external_id="image-1",
            name="Receipt.jpg",
            path="/Inbox/Receipt.jpg",
            mime_type="image/jpeg",
            extension="jpg",
            size_bytes=20,
        )
        document_file = _add_file(
            session,
            external_id="pdf-1",
            name="Budget.pdf",
            path="/Finance/Budget.pdf",
            mime_type="application/pdf",
            extension="pdf",
            size_bytes=30,
        )
        session.commit()

        created_jobs = enqueue_classification_backfill(session, limit=10)
        stored_jobs = session.scalars(select(ClassificationJob).order_by(ClassificationJob.id.asc())).all()
    finally:
        session.close()

    assert [job.file_id for job in created_jobs] == [
        document_file.id,
        image_file.id,
    ]
    assert [job.priority_bucket for job in stored_jobs] == [
        "document",
        "image",
    ]


def test_enqueue_classification_backfill_skips_matching_completed_state_and_active_jobs(
    tmp_path: Path,
):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()

    try:
        completed_file = _add_file(
            session,
            external_id="doc-1",
            name="Notes.txt",
            path="/Docs/Notes.txt",
            mime_type="text/plain",
            extension="txt",
            size_bytes=12,
        )
        active_job_file = _add_file(
            session,
            external_id="doc-2",
            name="Plan.txt",
            path="/Docs/Plan.txt",
            mime_type="text/plain",
            extension="txt",
            size_bytes=14,
        )
        session.add(
            ClassificationState(
                file_id=completed_file.id,
                source_fingerprint=compute_source_fingerprint(
                    file_record=completed_file,
                    extracted_content=None,
                ),
                source_size_bytes=12,
                submission_status=CLASSIFICATION_STATUS_COMPLETED,
            )
        )
        session.add(
            ClassificationJob(
                file_id=active_job_file.id,
                status=CLASSIFICATION_STATUS_QUEUED,
                priority_bucket="document",
                priority_rank=0,
                source_fingerprint="fp-active",
                max_attempts=DEFAULT_CLASSIFICATION_MAX_ATTEMPTS,
            )
        )
        session.commit()

        created_jobs = enqueue_classification_backfill(session, limit=10)
        stored_jobs = session.scalars(select(ClassificationJob).order_by(ClassificationJob.id.asc())).all()
    finally:
        session.close()

    assert created_jobs == []
    assert len(stored_jobs) == 1
    assert stored_jobs[0].file_id == active_job_file.id


def test_enqueue_classification_backfill_scans_past_completed_prefix_to_find_new_candidates(
    tmp_path: Path,
):
    session_factory = _build_session_factory(tmp_path)
    session = session_factory()

    try:
        for index in range(1, 8):
            file_record = _add_file(
                session,
                external_id=f"done-{index}",
                name=f"Done-{index}.pdf",
                path=f"/Archive/Done-{index}.pdf",
                mime_type="application/pdf",
                extension="pdf",
                size_bytes=10 + index,
            )
            session.add(
                ClassificationState(
                    file_id=file_record.id,
                    source_fingerprint=compute_source_fingerprint(
                        file_record=file_record,
                        extracted_content=None,
                    ),
                    source_size_bytes=file_record.size_bytes,
                    submission_status=CLASSIFICATION_STATUS_COMPLETED,
                )
            )

        pending_file = _add_file(
            session,
            external_id="pending-1",
            name="Pending.pdf",
            path="/Inbox/Pending.pdf",
            mime_type="application/pdf",
            extension="pdf",
            size_bytes=42,
        )
        session.commit()

        created_jobs = enqueue_classification_backfill(session, limit=1)
    finally:
        session.close()

    assert len(created_jobs) == 1
    assert created_jobs[0].file_id == pending_file.id


def test_run_next_classification_job_submits_file_and_persists_completed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mirror_root = tmp_path / "mirror"
    local_file = mirror_root / "Finance" / "Budget.pdf"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"pdf-bytes")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()

    try:
        file_record = _add_file(
            session,
            external_id="pdf-1",
            name="Budget.pdf",
            path="/Finance/Budget.pdf",
            mime_type="application/pdf",
            extension="pdf",
            size_bytes=9,
        )
        enqueue_classification_backfill(session, limit=10)
        client = FakeClassifierClient()

        completed_job = run_next_classification_job(
            session,
            client=client,
            worker_id="classifier-a",
        )
        state = session.scalar(
            select(ClassificationState).where(ClassificationState.file_id == file_record.id)
        )
    finally:
        session.close()

    assert completed_job is not None
    assert completed_job.status == CLASSIFICATION_STATUS_COMPLETED
    assert client.calls == [
        {
            "file_path": local_file,
            "file_name": "Budget.pdf",
            "canonical_source_path": str(local_file),
            "canonical_source_hash": "29d1283686193dc1461a7deac4f53d9bc5402a28b95d854f69e94986756fd0a9",
            "last_seen_filename": "Budget.pdf",
        }
    ]
    assert state is not None
    assert state.submission_status == CLASSIFICATION_STATUS_COMPLETED
    assert state.primary_label == "Finance"
    assert state.summary == "Quarterly budget draft"
    assert state.classifier_note_path == "01 Classified/finance/Budget.md"


def test_run_next_classification_job_retries_then_fails_after_attempt_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mirror_root = tmp_path / "mirror"
    local_file = mirror_root / "Docs" / "Plan.txt"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"plan")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()

    try:
        _add_file(
            session,
            external_id="txt-1",
            name="Plan.txt",
            path="/Docs/Plan.txt",
            mime_type="text/plain",
            extension="txt",
            size_bytes=4,
        )
        enqueue_classification_backfill(session, limit=10)
        failing_client = FakeClassifierClient(error=RuntimeError("classifier unavailable"))

        first_attempt = run_next_classification_job(
            session,
            client=failing_client,
            worker_id="classifier-a",
        )
        first_status = first_attempt.status
        second_attempt = run_next_classification_job(
            session,
            client=failing_client,
            worker_id="classifier-a",
        )
        second_status = second_attempt.status
        third_attempt = run_next_classification_job(
            session,
            client=failing_client,
            worker_id="classifier-a",
        )
        third_status = third_attempt.status
        stored_job = session.scalar(select(ClassificationJob).order_by(ClassificationJob.id.desc()).limit(1))
        stored_state = session.scalar(select(ClassificationState).limit(1))
    finally:
        session.close()

    assert first_attempt is not None
    assert first_status == CLASSIFICATION_STATUS_QUEUED
    assert second_attempt is not None
    assert second_status == CLASSIFICATION_STATUS_QUEUED
    assert third_attempt is not None
    assert third_status == CLASSIFICATION_STATUS_FAILED
    assert stored_job is not None
    assert stored_job.attempt_count == DEFAULT_CLASSIFICATION_MAX_ATTEMPTS
    assert stored_state is not None
    assert stored_state.submission_status == CLASSIFICATION_STATUS_FAILED
    assert "classifier unavailable" in (stored_state.last_error or "")


def test_classifier_api_client_treats_real_folder_readiness_conflict_as_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    local_file = tmp_path / "Pictures" / "Family.jpeg"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"jpeg-bytes")

    def _fake_post(*args, **kwargs):
        return httpx.Response(
            409,
            json={
                "detail": (
                    "Real-folder ingestion is blocked until readiness thresholds pass "
                    "and allow_real_ingestion is enabled: "
                    "manual-real-ingestion-enable-still-required"
                )
            },
            request=httpx.Request("POST", "http://classifier.local/classify/upload"),
        )

    monkeypatch.setattr(httpx, "post", _fake_post)
    client = ClassifierApiClient(
        base_url="http://classifier.local",
        api_token="secret",
    )

    with pytest.raises(ClassifierSubmissionNotReadyError):
        client.submit_file(file_path=local_file, file_name=local_file.name)


def test_classification_worker_once_processes_up_to_configured_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mirror_root = tmp_path / "mirror"
    for name in ("Alpha.txt", "Beta.txt", "Gamma.txt"):
        local_file = mirror_root / "Docs" / name
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_bytes(name.encode("utf-8"))

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_CONCURRENCY", "2")

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    verification_session = None

    try:
        for index, name in enumerate(("Alpha.txt", "Beta.txt", "Gamma.txt"), start=1):
            _add_file(
                session,
                external_id=f"txt-{index}",
                name=name,
                path=f"/Docs/{name}",
                mime_type="text/plain",
                extension="txt",
                size_bytes=len(name),
            )
        client = FakeClassifierClient()

        processed_count = run_classification_worker_once(
            session_factory=session_factory,
            worker_id="classifier-a",
            client=client,
        )

        verification_session = session_factory()
        try:
            completed_jobs = verification_session.scalars(
                select(ClassificationJob)
                .where(ClassificationJob.status == CLASSIFICATION_STATUS_COMPLETED)
                .order_by(ClassificationJob.id.asc())
            ).all()
            queued_jobs = verification_session.scalars(
                select(ClassificationJob)
                .where(ClassificationJob.status == CLASSIFICATION_STATUS_QUEUED)
                .order_by(ClassificationJob.id.asc())
            ).all()
        finally:
            verification_session.close()
    finally:
        try:
            session.close()
        except Exception:
            pass
        if verification_session is not None:
            verification_session.close()

    assert get_classification_submission_concurrency() == 2
    assert processed_count == 2
    assert len(completed_jobs) == 2
    assert len(queued_jobs) == 1
    assert len(client.calls) == 2


def test_classification_worker_once_runs_vault_reconciliation_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    session_factory = _build_session_factory(tmp_path)
    reconciliation_calls: list[int] = []

    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_ENABLED", "true")
    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_CONCURRENCY", "1")
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.enqueue_classification_backfill",
        lambda session, limit: [],
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.run_next_classification_job",
        lambda session, client, worker_id: None,
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.run_vault_reconciliation_once",
        lambda session, limit=None: reconciliation_calls.append(limit) or {
            "scanned": 0,
            "repaired": 0,
            "ambiguous": 0,
            "unverified": 0,
            "skipped": 0,
        },
        raising=False,
    )

    processed_count = run_classification_worker_once(
        session_factory=session_factory,
        worker_id="classifier-a",
        client=FakeClassifierClient(),
    )

    assert processed_count == 0
    assert reconciliation_calls == [None]
