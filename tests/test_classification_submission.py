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
    create_classifier_api_client,
    enqueue_classification_backfill,
    enqueue_targeted_reclassification_from_manual_feedback,
    get_classification_backfill_enabled,
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
                "entity_summary": "organizations: Finance Team",
                "topic_summary": "financial, budget",
                "retrieval_terms": ["budget", "finance", "forecast"],
                "retrieval_text": "Finance Team budget forecast draft",
            },
        }
        self._error = error
        self.calls: list[dict[str, object]] = []

    def submit_file(
        self,
        *,
        file_path: Path,
        file_name: str,
        source_relative_path: str | None = None,
        canonical_source_path: str | None = None,
        canonical_source_hash: str | None = None,
        last_seen_filename: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "file_path": file_path,
                "file_name": file_name,
                "source_relative_path": source_relative_path,
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
            "source_relative_path": "Finance/Budget.pdf",
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
    assert state.entity_summary == "organizations: Finance Team"
    assert state.topic_summary == "financial, budget"
    assert state.retrieval_terms_json == '["budget", "finance", "forecast"]'
    assert state.retrieval_text == "Finance Team budget forecast draft"


def test_run_next_classification_job_strips_nul_bytes_before_persisting_completed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mirror_root = tmp_path / "mirror"
    local_file = mirror_root / "Finance" / "Budget.txt"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"budget-text")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()

    nul_response = {
        "ok": True,
        "record": {
            "primary_label": "Tech\x00nical",
            "summary": "Quarterly\x00 budget draft",
            "confidence": 0.75,
            "reasoning": "Contains\x00 planning details.",
            "note_path": "01 Classified/technical/Budget\x00.md",
            "entity_summary": "teams:\x00 Finance",
            "topic_summary": "technical,\x00 budget",
            "retrieval_terms": ["budget", "tech\x00nical", "forecast"],
            "retrieval_text": "Budget\x00 retrieval text",
        },
        "stdout_tail": "ok\x00tail",
    }

    try:
        file_record = _add_file(
            session,
            external_id="txt-1",
            name="Budget.txt",
            path="/Finance/Budget.txt",
            mime_type="text/plain",
            extension="txt",
            size_bytes=11,
        )
        enqueue_classification_backfill(session, limit=10)
        client = FakeClassifierClient(response=nul_response)

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
    assert state is not None
    assert state.primary_label == "Technical"
    assert state.summary == "Quarterly budget draft"
    assert state.reasoning == "Contains planning details."
    assert state.classifier_note_path == "01 Classified/technical/Budget.md"
    assert state.entity_summary == "teams: Finance"
    assert state.topic_summary == "technical, budget"
    assert state.retrieval_terms_json == '["budget", "technical", "forecast"]'
    assert state.retrieval_text == "Budget retrieval text"
    assert "\x00" not in (state.classifier_manifest_record or "")
    assert "\x00" not in (state.response_payload_json or "")
    assert "\x00" not in (completed_job.classifier_response_json or "")


def test_run_next_classification_job_supports_nested_provider_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mirror_root = tmp_path / "mirrors"
    local_file = mirror_root / "google1" / "Shared" / "Budget.pdf"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"pdf-bytes")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()

    try:
        file_record = _add_file(
            session,
            external_id="pdf-google-1",
            name="Budget.pdf",
            path="/google1/Shared/Budget.pdf",
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
    assert client.calls[0]["file_path"] == local_file
    assert client.calls[0]["source_relative_path"] == "google1/Shared/Budget.pdf"
    assert client.calls[0]["canonical_source_path"] == str(local_file)
    assert state is not None
    assert state.submission_status == CLASSIFICATION_STATUS_COMPLETED


def test_classifier_api_client_uses_source_endpoint_for_real_folder_submissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    local_file = tmp_path / "Pictures" / "Family.jpeg"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"jpeg-bytes")
    captured: dict[str, object] = {}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        return httpx.Response(
            200,
            json={"ok": True, "record": {}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", _fake_post)
    client = ClassifierApiClient(
        base_url="http://classifier.local",
        api_token="secret",
        ingestion_mode="real-folder",
    )

    response = client.submit_file(
        file_path=local_file,
        file_name=local_file.name,
        source_relative_path="google2/Pictures/Family.jpeg",
        canonical_source_path="/srv/cloud-vault/mirrors/google2/Pictures/Family.jpeg",
        canonical_source_hash="abc123",
        last_seen_filename=local_file.name,
    )

    assert response["ok"] is True
    assert captured["url"] == "http://classifier.local/classify/source"
    assert captured["files"] is None
    assert captured["data"] == {
        "ingestion_mode": "real-folder",
        "source_relative_path": "google2/Pictures/Family.jpeg",
        "canonical_source_path": "/srv/cloud-vault/mirrors/google2/Pictures/Family.jpeg",
        "canonical_source_hash": "abc123",
        "last_seen_filename": "Family.jpeg",
    }


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


def test_run_next_classification_job_keeps_readiness_gated_failures_queued_without_penalty(
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
            external_id="txt-readiness-1",
            name="Plan.txt",
            path="/Docs/Plan.txt",
            mime_type="text/plain",
            extension="txt",
            size_bytes=4,
        )
        enqueue_classification_backfill(session, limit=10)
        gated_client = FakeClassifierClient(
            error=ClassifierSubmissionNotReadyError(
                "Classifier API not ready yet (409): "
                '{"detail":"Real-folder ingestion is blocked until readiness thresholds pass and '
                'allow_real_ingestion is enabled: shadow-queue-backlog-too-deep"}'
            )
        )

        first_attempt = run_next_classification_job(
            session,
            client=gated_client,
            worker_id="classifier-a",
        )
        second_attempt = run_next_classification_job(
            session,
            client=gated_client,
            worker_id="classifier-a",
        )
        third_attempt = run_next_classification_job(
            session,
            client=gated_client,
            worker_id="classifier-a",
        )
        stored_job = session.scalar(select(ClassificationJob).order_by(ClassificationJob.id.desc()).limit(1))
        stored_state = session.scalar(select(ClassificationState).limit(1))
    finally:
        session.close()

    assert first_attempt is not None
    assert first_attempt.status == CLASSIFICATION_STATUS_QUEUED
    assert second_attempt is not None
    assert second_attempt.status == CLASSIFICATION_STATUS_QUEUED
    assert third_attempt is not None
    assert third_attempt.status == CLASSIFICATION_STATUS_QUEUED
    assert stored_job is not None
    assert stored_job.attempt_count == 0
    assert stored_job.error_message is not None
    assert "without penalty" in stored_job.error_message
    assert stored_state is not None
    assert stored_state.submission_status == CLASSIFICATION_STATUS_QUEUED
    assert stored_state.last_error is not None
    assert "shadow-queue-backlog-too-deep" in stored_state.last_error


def test_create_classifier_api_client_requires_token_when_submission_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_ENABLED", "true")
    monkeypatch.delenv("CLASSIFIER_API_TOKEN", raising=False)

    with pytest.raises(
        ClassifierSubmissionNotReadyError,
        match="CLASSIFIER_API_TOKEN is required",
    ):
        create_classifier_api_client()


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
    targeted_requeue_calls: list[int] = []

    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_ENABLED", "true")
    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_CONCURRENCY", "1")
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.enqueue_classification_backfill",
        lambda session, limit: [],
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.enqueue_targeted_reclassification_from_manual_feedback",
        lambda session, limit: targeted_requeue_calls.append(limit) or [],
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.get_classification_targeted_requeue_limit",
        lambda: 10,
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
    assert targeted_requeue_calls == [10]
    assert reconciliation_calls == [None]


def test_classification_worker_once_can_skip_backfill_and_still_seed_targeted_requeue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    session_factory = _build_session_factory(tmp_path)
    backfill_calls: list[int] = []
    targeted_requeue_calls: list[int] = []

    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_ENABLED", "true")
    monkeypatch.setenv("CLASSIFICATION_BACKFILL_ENABLED", "false")
    monkeypatch.setenv("CLASSIFICATION_SUBMISSION_CONCURRENCY", "1")
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.enqueue_classification_backfill",
        lambda session, limit: backfill_calls.append(limit) or [],
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.enqueue_targeted_reclassification_from_manual_feedback",
        lambda session, limit: targeted_requeue_calls.append(limit) or [],
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.get_classification_targeted_requeue_limit",
        lambda: 10,
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.run_next_classification_job",
        lambda session, client, worker_id: None,
    )
    monkeypatch.setattr(
        "icloud_index_service.classification_worker.run_vault_reconciliation_once",
        lambda session, limit=None: {
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
    assert backfill_calls == []
    assert targeted_requeue_calls == [10]


def test_get_classification_backfill_enabled_defaults_true_and_honors_false_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("CLASSIFICATION_BACKFILL_ENABLED", raising=False)
    assert get_classification_backfill_enabled() is True

    monkeypatch.setenv("CLASSIFICATION_BACKFILL_ENABLED", "false")
    assert get_classification_backfill_enabled() is False


def test_enqueue_targeted_reclassification_from_manual_feedback_queues_strong_generated_note_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mirror_root = tmp_path / "mirrors"
    local_file = mirror_root / "icloud" / "Scanned" / "botox.pdf"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"botox-pdf")

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
                f'canonical_source_path: "{local_file}"',
                "---",
                "",
                "# botox.pdf",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("CLASSIFICATION_TARGETED_REQUEUE_ENABLED", "true")

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    try:
        file_record = _add_file(
            session,
            external_id="pdf-strong-1",
            name="botox.pdf",
            path="/icloud/Scanned/botox.pdf",
            mime_type="application/pdf",
            extension="pdf",
            size_bytes=len(b"botox-pdf"),
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
                primary_label="medical",
            )
        )
        session.commit()

        created_jobs = enqueue_targeted_reclassification_from_manual_feedback(session, limit=10)
        stored_jobs = session.scalars(select(ClassificationJob).order_by(ClassificationJob.id.asc())).all()
    finally:
        session.close()

    assert len(created_jobs) == 1
    assert created_jobs[0].file_id == file_record.id
    assert stored_jobs[0].status == CLASSIFICATION_STATUS_QUEUED
    assert stored_jobs[0].priority_bucket == "document"


def test_enqueue_targeted_reclassification_from_manual_feedback_skips_weak_folder_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mirror_root = tmp_path / "mirrors"
    local_file = mirror_root / "icloud" / "Scanned" / "manual-note.pdf"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"manual-pdf")

    vault_root = tmp_path / "vault"
    note_path = vault_root / "medical" / "manual-note.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# Manual note\n", encoding="utf-8")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("CLASSIFICATION_TARGETED_REQUEUE_ENABLED", "true")

    folder_map_path = tmp_path / "vault-folder-labels.json"
    folder_map_path.write_text('{"medical": {"primary_label": "medical"}}\n', encoding="utf-8")
    monkeypatch.setenv("CLASSIFIER_CONFIG_ROOT", str(tmp_path))

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    try:
        _add_file(
            session,
            external_id="pdf-weak-1",
            name="manual-note.pdf",
            path="/icloud/Scanned/manual-note.pdf",
            mime_type="application/pdf",
            extension="pdf",
            size_bytes=len(b"manual-pdf"),
        )
        created_jobs = enqueue_targeted_reclassification_from_manual_feedback(session, limit=10)
    finally:
        session.close()

    assert created_jobs == []


def test_enqueue_targeted_reclassification_from_manual_feedback_skips_when_feedback_is_older_than_last_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from datetime import datetime, timedelta, timezone

    mirror_root = tmp_path / "mirrors"
    local_file = mirror_root / "icloud" / "Scanned" / "botox.pdf"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"botox-pdf")

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
                f'canonical_source_path: "{local_file}"',
                "---",
                "",
                "# botox.pdf",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("CLASSIFICATION_TARGETED_REQUEUE_ENABLED", "true")

    session_factory = _build_session_factory(tmp_path)
    session = session_factory()
    try:
        file_record = _add_file(
            session,
            external_id="pdf-strong-2",
            name="botox.pdf",
            path="/icloud/Scanned/botox.pdf",
            mime_type="application/pdf",
            extension="pdf",
            size_bytes=len(b"botox-pdf"),
        )
        state = ClassificationState(
            file_id=file_record.id,
            source_fingerprint=compute_source_fingerprint(
                file_record=file_record,
                extracted_content=None,
            ),
            source_size_bytes=file_record.size_bytes,
            submission_status=CLASSIFICATION_STATUS_COMPLETED,
            primary_label="medical",
            last_completed_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        session.add(state)
        session.commit()

        created_jobs = enqueue_targeted_reclassification_from_manual_feedback(session, limit=10)
    finally:
        session.close()

    assert created_jobs == []
