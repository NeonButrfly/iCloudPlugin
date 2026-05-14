from __future__ import annotations

import copy
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from icloud_index_service.api.refresh import get_refresh_status, request_refresh
import icloud_index_service.services.job_runner as job_runner_module
import icloud_index_service.worker as worker_module
from icloud_index_service.models.base import Base
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.job import Job
from icloud_index_service.models.sync_run import SyncRun
from icloud_index_service.services.crawler import normalize_remote_item
from icloud_index_service.services.icloud_web_client import ICloudWebClient
from icloud_index_service.services.job_runner import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    METADATA_REFRESH_JOB_TYPE,
    apply_running_job_lease_update,
    SchemaNotReadyError,
    apply_stale_recovery_update,
    claim_next_metadata_refresh_job,
    enqueue_metadata_refresh,
    recover_stale_running_jobs,
    renew_refresh_job_heartbeat,
    run_next_job,
)
from icloud_index_service.worker import run_worker_loop


def _build_session_factory(tmp_path: Path, *, create_schema: bool) -> sessionmaker[Session]:
    database_path = tmp_path / "task5.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    if create_schema:
        assert SyncRun.__table__.name == "sync_runs"
        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _build_session_factory_without_active_refresh_index(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "task5-no-index.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE sync_runs (
                id INTEGER PRIMARY KEY,
                status VARCHAR(50) NOT NULL,
                started_at DATETIME,
                completed_at DATETIME,
                error_message TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                job_type VARCHAR(100) NOT NULL,
                status VARCHAR(50) NOT NULL,
                payload_json TEXT,
                error_message TEXT,
                sync_run_id INTEGER,
                FOREIGN KEY(sync_run_id) REFERENCES sync_runs(id)
            )
            """
        )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class FakeICloudWebClient(ICloudWebClient):
    def __init__(self, remote_items: list[dict[str, object]]) -> None:
        super().__init__(auth_mode="browser-assisted-apple-web")
        self._remote_items = remote_items

    def list_drive_items(self, *, heartbeat=None) -> list[dict[str, object]]:
        if heartbeat is not None:
            heartbeat()
        return list(self._remote_items)


class TransientFailureICloudWebClient(ICloudWebClient):
    def list_drive_items(self, *, heartbeat=None) -> list[dict[str, object]]:
        if heartbeat is not None:
            heartbeat()
        raise RuntimeError("temporary upstream failure")


class ClaimStealingICloudWebClient(ICloudWebClient):
    def __init__(self, steal_claim) -> None:
        super().__init__(auth_mode="browser-assisted-apple-web")
        self._steal_claim = steal_claim

    def list_drive_items(self, *, heartbeat=None) -> list[dict[str, object]]:
        if heartbeat is not None:
            heartbeat()
        self._steal_claim()
        return [
            {
                "id": "abc",
                "name": "Notes",
                "path": "/Work/Notes.md",
                "extension": "md",
                "contentType": "text/markdown",
            }
        ]


class LeaseLosingICloudWebClient(ICloudWebClient):
    def __init__(self, steal_claim) -> None:
        super().__init__(auth_mode="browser-assisted-apple-web")
        self._steal_claim = steal_claim
        self.continued_after_heartbeat = False

    def list_drive_items(self, *, heartbeat=None) -> list[dict[str, object]]:
        self._steal_claim()
        if heartbeat is not None:
            heartbeat()
        self.continued_after_heartbeat = True
        return [
            {
                "id": "abc",
                "name": "Notes",
                "path": "/Work/Notes.md",
                "extension": "md",
                "contentType": "text/markdown",
            }
        ]


class ExtractingICloudWebClient(ICloudWebClient):
    def __init__(self) -> None:
        super().__init__(auth_mode="browser-assisted-apple-web")

    def list_drive_items(self, *, heartbeat=None) -> list[dict[str, object]]:
        if heartbeat is not None:
            heartbeat()
        return [
            {
                "id": "budget-file",
                "name": "Budget.txt",
                "path": "/Finance/Budget.txt",
                "extension": "txt",
                "contentType": "text/plain",
                "content_bytes": b"Quarterly budget draft",
                "size": 24,
            }
        ]


class SingleItemICloudWebClient(ICloudWebClient):
    def __init__(self, raw_item: dict[str, object]) -> None:
        super().__init__(auth_mode="browser-assisted-apple-web")
        self._raw_item = raw_item

    def list_drive_items(self, *, heartbeat=None) -> list[dict[str, object]]:
        if heartbeat is not None:
            heartbeat()
        return [dict(self._raw_item)]


class BatchingICloudWebClient(ICloudWebClient):
    def __init__(
        self,
        *,
        initial_frontier: list[dict[str, object]],
        batches: list[tuple[list[dict[str, object]], list[dict[str, object]], bool]],
    ) -> None:
        super().__init__(auth_mode="browser-assisted-apple-web")
        self._initial_frontier = copy.deepcopy(initial_frontier)
        self._batches = list(batches)
        self.frontier_calls: list[list[dict[str, object]]] = []

    def build_traversal_frontier(self) -> list[dict[str, object]]:
        return copy.deepcopy(self._initial_frontier)

    def list_drive_items_batch(self, frontier, *, limit, heartbeat=None):
        if heartbeat is not None:
            heartbeat()
        self.frontier_calls.append(copy.deepcopy(frontier))
        raw_items, next_frontier, completed_snapshot = self._batches.pop(0)
        return (
            copy.deepcopy(raw_items),
            copy.deepcopy(next_frontier),
            completed_snapshot,
        )


def test_normalize_remote_item_preserves_storage_shape_for_later_routing():
    raw = {
        "id": "abc",
        "name": "Notes",
        "path": "/Work/Notes.md",
        "extension": "md",
        "contentType": "text/markdown",
    }

    normalized = normalize_remote_item(raw)

    assert normalized == {
        "external_id": "abc",
        "name": "Notes",
        "path": "/Work/Notes.md",
        "extension": "md",
        "mime_type": "text/markdown",
        "size_bytes": None,
    }


def test_request_refresh_surfaces_missing_job_schema_before_queueing(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=False)
    session = session_factory()

    try:
        with pytest.raises(HTTPException) as exc_info:
            request_refresh(session)
    finally:
        session.close()

    assert exc_info.value.status_code == 503
    assert "missing tables" in exc_info.value.detail
    assert "jobs" in exc_info.value.detail
    assert "sync_runs" in exc_info.value.detail


def test_request_refresh_surfaces_missing_active_refresh_index_until_follow_up_migration_applies(
    tmp_path,
):
    session_factory = _build_session_factory_without_active_refresh_index(tmp_path)
    session = session_factory()

    try:
        with pytest.raises(HTTPException) as exc_info:
            request_refresh(session)
    finally:
        session.close()

    assert exc_info.value.status_code == 503
    assert "uq_jobs_active_metadata_refresh" in exc_info.value.detail
    assert "migration" in exc_info.value.detail.lower()


def test_refresh_status_reports_latest_job_progress(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        idle_payload = get_refresh_status(session)
        session.add(
            Job(
                job_type=METADATA_REFRESH_JOB_TYPE,
                status=JOB_STATUS_RUNNING,
                payload_json=json.dumps(
                    {
                        "source": "background-scan",
                        "items_seen": 25,
                        "batch_count": 3,
                        "frontier": [{"type": "folder", "name": "Documents"}],
                    }
                ),
                sync_run_id=None,
            )
        )
        session.commit()
        active_payload = get_refresh_status(session)
    finally:
        session.close()

    assert idle_payload == {"status": "idle"}
    assert active_payload == {
        "status": "running",
        "job_id": 1,
        "job_type": "metadata-refresh",
        "source": "background-scan",
        "items_seen": 25,
        "batch_count": 3,
        "sync_run_id": None,
        "error_message": None,
        "frontier_length": 1,
    }


def test_refresh_job_schema_readiness_caches_success_by_bind(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    first_session = session_factory()
    second_session = session_factory()
    inspect_calls = 0
    real_inspect = job_runner_module.inspect

    def counting_inspect(bind):
        nonlocal inspect_calls
        inspect_calls += 1
        return real_inspect(bind)

    monkeypatch.setattr(job_runner_module, "_SCHEMA_READY_CACHE", {})
    monkeypatch.setattr(job_runner_module, "inspect", counting_inspect)

    try:
        job_runner_module.ensure_refresh_job_schema_ready(first_session)
        job_runner_module.ensure_refresh_job_schema_ready(first_session)
        job_runner_module.ensure_refresh_job_schema_ready(second_session)
    finally:
        first_session.close()
        second_session.close()

    assert inspect_calls == 1


def test_enqueue_and_run_metadata_refresh_updates_job_payload_with_crawl_results(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        queued_job = enqueue_metadata_refresh(session)
        queued_job_status = queued_job.status
        completed_job = run_next_job(
            session,
            client=FakeICloudWebClient(
                [
                    {
                        "id": "abc",
                        "name": "Notes",
                        "path": "/Work/Notes.md",
                        "extension": "md",
                        "contentType": "text/markdown",
                    }
                ]
            ),
        )
        stored_job = session.scalar(select(Job).where(Job.id == queued_job.id))
    finally:
        session.close()

    assert queued_job.job_type == METADATA_REFRESH_JOB_TYPE
    assert queued_job_status == JOB_STATUS_QUEUED
    assert completed_job is not None
    assert completed_job.status == JOB_STATUS_COMPLETED
    assert completed_job.error_message is None
    assert json.loads(completed_job.payload_json or "{}") == {
        "source": "refresh-endpoint",
        "items_seen": 1,
        "auth_mode": "browser-assisted-apple-web",
    }
    assert stored_job is not None
    assert stored_job.status == JOB_STATUS_COMPLETED


def test_run_next_job_requeues_partial_refresh_and_resumes_from_persisted_frontier(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()
    client = BatchingICloudWebClient(
        initial_frontier=[
            {
                "type": "folder",
                "name": "root",
                "path": "",
                "drivewsid": "root",
            }
        ],
        batches=[
            (
                [
                    {
                        "id": "file-1",
                        "name": "File1.txt",
                        "path": "/Docs/File1.txt",
                        "extension": "txt",
                        "contentType": "text/plain",
                        "size": 10,
                    }
                ],
                [
                    {
                        "type": "file",
                        "name": "File2.txt",
                        "path": "/Docs/File2.txt",
                        "drivewsid": "file-2",
                        "docwsid": "file-2",
                        "zone": "com.apple.CloudDocs",
                        "size": 12,
                    }
                ],
                False,
            ),
            (
                [
                    {
                        "id": "file-2",
                        "name": "File2.txt",
                        "path": "/Docs/File2.txt",
                        "extension": "txt",
                        "contentType": "text/plain",
                        "size": 12,
                    }
                ],
                [],
                True,
            ),
        ],
    )

    try:
        queued_job = enqueue_metadata_refresh(session)
        first_result = run_next_job(session, client=client, worker_id="worker-a")
        first_status = first_result.status
        first_payload = json.loads(first_result.payload_json or "{}")
        stored_job_after_first_batch = session.scalar(select(Job).where(Job.id == queued_job.id))
        first_sync_run_id = stored_job_after_first_batch.sync_run_id
        stored_file_after_first_batch = session.scalar(
            select(FileRecord).where(FileRecord.external_id == "file-1")
        )

        second_result = run_next_job(session, client=client, worker_id="worker-a")
        second_payload = json.loads(second_result.payload_json or "{}")
        stored_job_after_second_batch = session.scalar(select(Job).where(Job.id == queued_job.id))
        stored_files = session.scalars(select(FileRecord).order_by(FileRecord.external_id.asc())).all()
        sync_run = session.scalar(select(SyncRun).where(SyncRun.id == first_sync_run_id))
    finally:
        session.close()

    assert first_result is not None
    assert first_status == JOB_STATUS_QUEUED
    assert first_payload["items_seen"] == 1
    assert first_payload["batch_count"] == 1
    assert len(first_payload["frontier"]) == 1
    assert stored_job_after_first_batch is not None
    assert stored_job_after_first_batch.sync_run_id is not None
    assert stored_file_after_first_batch is not None
    assert stored_file_after_first_batch.last_seen_sync_run_id == stored_job_after_first_batch.sync_run_id

    assert second_result is not None
    assert second_result.status == JOB_STATUS_COMPLETED
    assert second_payload["items_seen"] == 2
    assert "frontier" not in second_payload
    assert stored_job_after_second_batch is not None
    assert stored_job_after_second_batch.sync_run_id == first_sync_run_id
    assert [file.external_id for file in stored_files] == ["file-1", "file-2"]
    assert sync_run is not None
    assert sync_run.status == JOB_STATUS_COMPLETED
    assert client.frontier_calls[0] == [
        {
            "type": "folder",
            "name": "root",
            "path": "",
            "drivewsid": "root",
        }
    ]
    assert client.frontier_calls[1] == first_payload["frontier"]


def test_run_next_job_persists_file_records_and_extracted_content_from_refresh_results(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()
    extraction_calls: list[dict[str, object]] = []

    def fake_extract_text_content(*, path: str, mime_type: str, payload: bytes) -> str:
        extraction_calls.append(
            {
                "path": path,
                "mime_type": mime_type,
                "payload": payload,
            }
        )
        return "Quarterly budget draft"

    monkeypatch.setattr(job_runner_module, "extract_text_content", fake_extract_text_content)

    try:
        enqueue_metadata_refresh(session)
        completed_job = run_next_job(session, client=ExtractingICloudWebClient())
        stored_file = session.scalar(
            select(FileRecord).where(FileRecord.external_id == "budget-file")
        )
        stored_content = session.scalar(
            select(ExtractedContent).join(
                FileRecord,
                ExtractedContent.file_id == FileRecord.id,
            )
            .where(FileRecord.external_id == "budget-file")
        )
    finally:
        session.close()

    assert completed_job is not None
    assert completed_job.status == JOB_STATUS_COMPLETED
    assert extraction_calls == [
        {
            "path": "/Finance/Budget.txt",
            "mime_type": "text/plain",
            "payload": b"Quarterly budget draft",
        }
    ]
    assert stored_file is not None
    assert stored_file.name == "Budget.txt"
    assert stored_file.path == "/Finance/Budget.txt"
    assert stored_file.mime_type == "text/plain"
    assert stored_file.size_bytes == 24
    assert stored_content is not None
    assert stored_content.content_text == "Quarterly budget draft"


def test_run_next_job_marks_missing_files_as_deleted_when_they_disappear_from_refresh(
    tmp_path,
):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        stale_file = FileRecord(
            external_id="missing-file",
            name="Missing.txt",
            path="/Finance/Missing.txt",
            mime_type="text/plain",
            size_bytes=10,
        )
        current_file = FileRecord(
            external_id="current-file",
            name="Current.txt",
            path="/Finance/Current.txt",
            mime_type="text/plain",
            size_bytes=12,
        )
        session.add_all([stale_file, current_file])
        session.commit()

        enqueue_metadata_refresh(session)
        completed_job = run_next_job(
            session,
            client=FakeICloudWebClient(
                [
                    {
                        "id": "current-file",
                        "name": "Current.txt",
                        "path": "/Finance/Current.txt",
                        "extension": "txt",
                        "contentType": "text/plain",
                        "content_bytes": b"current file",
                        "size": 12,
                    }
                ]
            ),
        )
        reloaded_stale_file = session.scalar(
            select(FileRecord).where(FileRecord.external_id == "missing-file")
        )
        reloaded_current_file = session.scalar(
            select(FileRecord).where(FileRecord.external_id == "current-file")
        )
    finally:
        session.close()

    assert completed_job is not None
    assert completed_job.status == JOB_STATUS_COMPLETED
    assert reloaded_stale_file is not None
    assert reloaded_stale_file.is_deleted is True
    assert reloaded_current_file is not None
    assert reloaded_current_file.is_deleted is False


def test_run_next_job_marks_all_files_deleted_when_a_complete_refresh_is_empty(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        session.add(
            FileRecord(
                external_id="missing-file",
                name="Missing.txt",
                path="/Finance/Missing.txt",
                mime_type="text/plain",
                size_bytes=10,
            )
        )
        session.commit()

        enqueue_metadata_refresh(session)
        completed_job = run_next_job(session, client=FakeICloudWebClient([]))
        reloaded_file = session.scalar(
            select(FileRecord).where(FileRecord.external_id == "missing-file")
        )
    finally:
        session.close()

    assert completed_job is not None
    assert completed_job.status == JOB_STATUS_COMPLETED
    assert reloaded_file is not None
    assert reloaded_file.is_deleted is True


@pytest.mark.parametrize(
    ("raw_item", "patched_extracted_text"),
    [
        (
            {
                "id": "budget-file",
                "name": "Budget.txt",
                "path": "/Finance/Budget.txt",
                "extension": "txt",
                "contentType": "text/plain",
                "size": 24,
            },
            None,
        ),
        (
            {
                "id": "budget-file",
                "name": "Budget.bin",
                "path": "/Finance/Budget.bin",
                "extension": "bin",
                "contentType": "application/octet-stream",
                "content_bytes": b"\x00\x01\x02",
                "size": 3,
            },
            None,
        ),
        (
            {
                "id": "budget-file",
                "name": "Budget.txt",
                "path": "/Finance/Budget.txt",
                "extension": "txt",
                "contentType": "text/plain",
                "content_bytes": b"",
                "size": 0,
            },
            "",
        ),
    ],
)
def test_run_next_job_clears_stale_extracted_content_when_refresh_can_no_longer_extract_text(
    tmp_path,
    monkeypatch,
    raw_item,
    patched_extracted_text,
):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    if patched_extracted_text is not None:
        monkeypatch.setattr(
            job_runner_module,
            "extract_text_content",
            lambda **kwargs: patched_extracted_text,
        )

    try:
        file_record = FileRecord(
            external_id="budget-file",
            name="Budget.txt",
            path="/Finance/Budget.txt",
            mime_type="text/plain",
            size_bytes=24,
        )
        session.add(file_record)
        session.commit()
        session.refresh(file_record)
        session.add(
            ExtractedContent(
                file_id=file_record.id,
                content_text="stale extracted text",
                content_hash="stale-hash",
            )
        )
        session.commit()

        enqueue_metadata_refresh(session)
        completed_job = run_next_job(session, client=SingleItemICloudWebClient(raw_item))
        stored_file = session.scalar(
            select(FileRecord).where(FileRecord.external_id == "budget-file")
        )
        stored_content = session.scalar(
            select(ExtractedContent).where(ExtractedContent.file_id == file_record.id)
        )
    finally:
        session.close()

    assert completed_job is not None
    assert completed_job.status == JOB_STATUS_COMPLETED
    assert stored_file is not None
    assert stored_content is None


def test_run_next_job_treats_extraction_failures_as_best_effort_and_keeps_refresh_completed(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    def fake_extract_text_content(*, path: str, mime_type: str, payload: bytes) -> str:
        if path.endswith("Broken.txt"):
            raise RuntimeError("parser exploded")
        return "Good extracted text"

    monkeypatch.setattr(job_runner_module, "extract_text_content", fake_extract_text_content)

    try:
        stale_file = FileRecord(
            external_id="broken-file",
            name="Broken.txt",
            path="/Finance/Broken.txt",
            mime_type="text/plain",
            size_bytes=20,
        )
        session.add(stale_file)
        session.commit()
        session.refresh(stale_file)
        session.add(
            ExtractedContent(
                file_id=stale_file.id,
                content_text="stale extracted text",
                content_hash="stale-hash",
            )
        )
        session.commit()

        enqueue_metadata_refresh(session)
        completed_job = run_next_job(
            session,
            client=FakeICloudWebClient(
                [
                    {
                        "id": "broken-file",
                        "name": "Broken.txt",
                        "path": "/Finance/Broken.txt",
                        "extension": "txt",
                        "contentType": "text/plain",
                        "content_bytes": b"bad payload",
                        "size": 20,
                    },
                    {
                        "id": "good-file",
                        "name": "Good.txt",
                        "path": "/Finance/Good.txt",
                        "extension": "txt",
                        "contentType": "text/plain",
                        "content_bytes": b"good payload",
                        "size": 12,
                    },
                ]
            ),
        )
        broken_content = session.scalar(
            select(ExtractedContent).where(ExtractedContent.file_id == stale_file.id)
        )
        good_file = session.scalar(
            select(FileRecord).where(FileRecord.external_id == "good-file")
        )
        good_content = session.scalar(
            select(ExtractedContent).join(
                FileRecord,
                ExtractedContent.file_id == FileRecord.id,
            )
            .where(FileRecord.external_id == "good-file")
        )
    finally:
        session.close()

    assert completed_job is not None
    assert completed_job.status == JOB_STATUS_COMPLETED
    assert json.loads(completed_job.payload_json or "{}")["extraction_failures"] == [
        {
            "external_id": "broken-file",
            "path": "/Finance/Broken.txt",
            "error": "RuntimeError: parser exploded",
        }
    ]
    assert broken_content is not None
    assert broken_content.content_text == "stale extracted text"
    assert good_file is not None
    assert good_content is not None
    assert good_content.content_text == "Good extracted text"


def test_claim_next_metadata_refresh_job_only_allows_one_worker_to_claim_same_job(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    setup_session = session_factory()
    try:
        queued_job = enqueue_metadata_refresh(setup_session)
    finally:
        setup_session.close()

    first_session = session_factory()
    second_session = session_factory()

    try:
        first_claim = claim_next_metadata_refresh_job(
            first_session,
            worker_id="worker-a",
        )
        second_claim = claim_next_metadata_refresh_job(
            second_session,
            worker_id="worker-b",
        )
    finally:
        first_session.close()
        second_session.close()

    assert first_claim is not None
    assert first_claim.id == queued_job.id
    assert first_claim.status == JOB_STATUS_RUNNING
    assert second_claim is None


def test_claim_next_metadata_refresh_job_does_not_increment_attempt_count_before_a_failure(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        enqueue_metadata_refresh(session)
        claimed_job = claim_next_metadata_refresh_job(session, worker_id="worker-a")
    finally:
        session.close()

    claimed_payload = json.loads(claimed_job.payload_json or "{}")

    assert claimed_job is not None
    assert claimed_job.status == JOB_STATUS_RUNNING
    assert claimed_payload["attempt_count"] == 0
    assert claimed_payload["max_attempts"] == 3


def test_recover_stale_running_jobs_requeues_expired_claims(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        stale_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "worker_id": "worker-a",
                    "claimed_at": (
                        datetime.now(timezone.utc) - timedelta(minutes=30)
                    ).isoformat(),
                }
            ),
        )
        session.add(stale_job)
        session.commit()
        session.refresh(stale_job)

        recovered_count = recover_stale_running_jobs(session, stale_after_seconds=60)
        reloaded_job = session.scalar(select(Job).where(Job.id == stale_job.id))
    finally:
        session.close()

    assert recovered_count == 1
    assert reloaded_job is not None
    assert reloaded_job.status == JOB_STATUS_QUEUED
    recovered_payload = json.loads(reloaded_job.payload_json or "{}")
    assert "attempt_count" not in recovered_payload
    assert "claimed_at" not in recovered_payload
    assert "worker_id" not in recovered_payload
    assert reloaded_job.error_message is not None
    assert "without penalty" in reloaded_job.error_message.lower()


def test_apply_stale_recovery_update_skips_job_when_lease_changed_since_snapshot(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    snapshot_session = session_factory()
    heartbeat_session = session_factory()

    claimed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    try:
        running_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "claimed_at": claimed_at.isoformat(),
                    "heartbeat_at": claimed_at.isoformat(),
                }
            ),
        )
        snapshot_session.add(running_job)
        snapshot_session.commit()
        snapshot_session.refresh(running_job)

        snapshot_payload_json = running_job.payload_json

        renew_refresh_job_heartbeat(
            heartbeat_session,
            running_job.id,
            now=claimed_at + timedelta(minutes=5),
        )

        recovery_applied = apply_stale_recovery_update(
            snapshot_session,
            job_id=running_job.id,
            expected_payload_json=snapshot_payload_json,
            next_status=JOB_STATUS_QUEUED,
            next_payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "attempt_count": 1,
                    "max_attempts": 3,
                }
            ),
            error_message="Recovered stale running job so it can be retried by the worker.",
        )

        reloaded_job = heartbeat_session.scalar(select(Job).where(Job.id == running_job.id))
    finally:
        snapshot_session.close()
        heartbeat_session.close()

    assert recovery_applied is False
    assert reloaded_job is not None
    assert reloaded_job.status == JOB_STATUS_RUNNING
    assert json.loads(reloaded_job.payload_json or "{}")["heartbeat_at"] == (
        claimed_at + timedelta(minutes=5)
    ).isoformat()


def test_renew_refresh_job_heartbeat_skips_stale_worker_when_lease_changed(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    first_session = session_factory()
    second_session = session_factory()
    claimed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    try:
        running_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "worker_id": "worker-a",
                    "claimed_at": claimed_at.isoformat(),
                    "heartbeat_at": claimed_at.isoformat(),
                }
            ),
        )
        first_session.add(running_job)
        first_session.commit()
        first_session.refresh(running_job)

        stale_snapshot_payload_json = running_job.payload_json

        running_job.payload_json = json.dumps(
            {
                "source": "refresh-endpoint",
                "attempt_count": 0,
                "max_attempts": 3,
                "worker_id": "worker-b",
                "claimed_at": (claimed_at + timedelta(minutes=5)).isoformat(),
                "heartbeat_at": (claimed_at + timedelta(minutes=5)).isoformat(),
            }
        )
        second_session.merge(running_job)
        second_session.commit()

        renewed_job = renew_refresh_job_heartbeat(
            first_session,
            running_job.id,
            expected_payload_json=stale_snapshot_payload_json,
            now=claimed_at + timedelta(minutes=10),
        )
        reloaded_job = second_session.scalar(select(Job).where(Job.id == running_job.id))
    finally:
        first_session.close()
        second_session.close()

    assert renewed_job is None
    assert reloaded_job is not None
    assert json.loads(reloaded_job.payload_json or "{}")["worker_id"] == "worker-b"
    assert json.loads(reloaded_job.payload_json or "{}")["heartbeat_at"] == (
        claimed_at + timedelta(minutes=5)
    ).isoformat()


def test_renew_refresh_job_heartbeat_keeps_a_running_job_out_of_stale_recovery(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()
    claimed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    try:
        running_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "claimed_at": claimed_at.isoformat(),
                    "heartbeat_at": claimed_at.isoformat(),
                }
            ),
        )
        session.add(running_job)
        session.commit()
        session.refresh(running_job)

        renew_refresh_job_heartbeat(
            session,
            running_job.id,
            now=claimed_at + timedelta(minutes=10),
        )
        recovered_count = recover_stale_running_jobs(
            session,
            stale_after_seconds=60,
            now=claimed_at + timedelta(minutes=10, seconds=30),
        )
        reloaded_job = session.scalar(select(Job).where(Job.id == running_job.id))
    finally:
        session.close()

    assert recovered_count == 0
    assert reloaded_job is not None
    assert reloaded_job.status == JOB_STATUS_RUNNING


def test_recover_stale_running_jobs_requeues_rows_without_valid_claimed_at(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        missing_claim_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps({"source": "refresh-endpoint"}),
        )
        session.add(missing_claim_job)
        session.commit()

        first_recovered_count = recover_stale_running_jobs(session, stale_after_seconds=60)
        first_stored_job = session.scalar(select(Job).where(Job.id == missing_claim_job.id))
        first_stored_job.status = JOB_STATUS_COMPLETED
        session.commit()
        first_stored_job_status = first_stored_job.status

        malformed_claim_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "claimed_at": "not-a-timestamp",
                }
            ),
        )
        session.add(malformed_claim_job)
        session.commit()
        second_recovered_count = recover_stale_running_jobs(session, stale_after_seconds=60)
        second_stored_job = session.scalar(select(Job).where(Job.id == malformed_claim_job.id))
    finally:
        session.close()

    assert first_recovered_count == 1
    assert first_stored_job_status == JOB_STATUS_COMPLETED
    assert second_recovered_count == 1
    assert second_stored_job is not None
    assert second_stored_job.status == JOB_STATUS_QUEUED
    assert second_stored_job.error_message is not None
    assert "without penalty" in second_stored_job.error_message.lower()


def test_recover_stale_running_jobs_does_not_consume_retry_budget(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        stale_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "attempt_count": 2,
                    "max_attempts": 3,
                    "claimed_at": (
                        datetime.now(timezone.utc) - timedelta(minutes=30)
                    ).isoformat(),
                }
            ),
        )
        session.add(stale_job)
        session.commit()
        session.refresh(stale_job)

        recovered_count = recover_stale_running_jobs(session, stale_after_seconds=60)
        reloaded_job = session.scalar(select(Job).where(Job.id == stale_job.id))
    finally:
        session.close()

    reloaded_payload = json.loads(reloaded_job.payload_json or "{}")

    assert recovered_count == 1
    assert reloaded_job is not None
    assert reloaded_job.status == JOB_STATUS_QUEUED
    assert reloaded_payload["attempt_count"] == 2
    assert reloaded_payload["max_attempts"] == 3
    assert reloaded_job.error_message is not None
    assert "without penalty" in reloaded_job.error_message.lower()


def test_run_next_job_resumes_recovered_stale_job_from_saved_frontier_and_sync_run(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    setup_session = session_factory()
    stale_claimed_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    existing_sync_run = SyncRun(status=JOB_STATUS_RUNNING)
    recovered_frontier = [
        {
            "type": "file",
            "name": "Recovered.txt",
            "path": "/Docs/Recovered.txt",
            "drivewsid": "file-recovered",
            "docwsid": "file-recovered",
            "zone": "com.apple.CloudDocs",
            "size": 12,
        }
    ]
    client = BatchingICloudWebClient(
        initial_frontier=[
            {
                "type": "folder",
                "name": "root",
                "path": "",
                "drivewsid": "root",
            }
        ],
        batches=[
            (
                [
                    {
                        "id": "file-recovered",
                        "name": "Recovered.txt",
                        "path": "/Docs/Recovered.txt",
                        "extension": "txt",
                        "contentType": "text/plain",
                        "size": 12,
                    }
                ],
                [],
                True,
            ),
        ],
    )

    try:
        setup_session.add(existing_sync_run)
        setup_session.commit()
        setup_session.refresh(existing_sync_run)

        stale_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            sync_run_id=existing_sync_run.id,
            payload_json=json.dumps(
                {
                    "source": "background-scan",
                    "attempt_count": 2,
                    "max_attempts": 3,
                    "worker_id": "worker-a",
                    "claimed_at": stale_claimed_at.isoformat(),
                    "heartbeat_at": stale_claimed_at.isoformat(),
                    "frontier": recovered_frontier,
                    "items_seen": 300,
                    "batch_count": 3,
                }
            ),
        )
        setup_session.add(stale_job)
        setup_session.commit()
        setup_session.refresh(stale_job)
        setup_session.close()

        recovery_session = session_factory()
        recovered_count = recover_stale_running_jobs(recovery_session, stale_after_seconds=60)
        recovered_job = recovery_session.scalar(select(Job).where(Job.id == stale_job.id))
        recovery_session.close()

        run_session = session_factory()
        completed_job = run_next_job(run_session, client=client, worker_id="worker-b")
        stored_job = run_session.scalar(select(Job).where(Job.id == stale_job.id))
        stored_sync_run = run_session.scalar(
            select(SyncRun).where(SyncRun.id == existing_sync_run.id)
        )
    finally:
        try:
            run_session.close()
        except Exception:
            pass

    assert recovered_count == 1
    assert recovered_job is not None
    assert recovered_job.status == JOB_STATUS_QUEUED
    assert completed_job is not None
    assert completed_job.id == stale_job.id
    assert completed_job.status == JOB_STATUS_COMPLETED
    assert stored_job is not None
    assert stored_job.sync_run_id == existing_sync_run.id
    assert stored_sync_run is not None
    assert stored_sync_run.status == JOB_STATUS_COMPLETED
    assert client.frontier_calls == [recovered_frontier]


def test_run_next_job_marks_placeholder_client_as_failed_not_completed(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        queued_job = enqueue_metadata_refresh(session)
        failed_job = run_next_job(session)
        stored_job = session.scalar(select(Job).where(Job.id == queued_job.id))
    finally:
        session.close()

    assert failed_job is not None
    assert failed_job.status == JOB_STATUS_FAILED
    assert failed_job.error_message is not None
    assert "not ready" in failed_job.error_message.lower()
    assert stored_job is not None
    assert stored_job.status == JOB_STATUS_FAILED


def test_run_next_job_aborts_immediately_when_heartbeat_loses_lease(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    setup_session = session_factory()
    claimed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    try:
        queued_job = enqueue_metadata_refresh(setup_session)
    finally:
        setup_session.close()

    def steal_claim() -> None:
        stealing_session = session_factory()
        try:
            stolen_job = stealing_session.scalar(select(Job).where(Job.id == queued_job.id))
            assert stolen_job is not None
            stolen_job.payload_json = json.dumps(
                {
                    "source": "refresh-endpoint",
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "worker_id": "worker-b",
                    "claimed_at": (claimed_at + timedelta(minutes=5)).isoformat(),
                    "heartbeat_at": (claimed_at + timedelta(minutes=5)).isoformat(),
                }
            )
            stealing_session.commit()
        finally:
            stealing_session.close()

    client = LeaseLosingICloudWebClient(steal_claim)
    worker_session = session_factory()
    verification_session = session_factory()

    try:
        result = run_next_job(
            worker_session,
            client=client,
            worker_id="worker-a",
            now=claimed_at,
        )
        stored_job = verification_session.scalar(select(Job).where(Job.id == queued_job.id))
    finally:
        worker_session.close()
        verification_session.close()

    assert result is None
    assert client.continued_after_heartbeat is False
    assert stored_job is not None
    assert stored_job.status == JOB_STATUS_RUNNING
    assert json.loads(stored_job.payload_json or "{}")["worker_id"] == "worker-b"


def test_apply_running_job_lease_update_skips_stale_worker_completion_when_lease_changed(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    primary_session = session_factory()
    stealing_session = session_factory()
    verification_session = session_factory()
    claimed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    try:
        running_job = Job(
            job_type=METADATA_REFRESH_JOB_TYPE,
            status=JOB_STATUS_RUNNING,
            payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "worker_id": "worker-a",
                    "claimed_at": claimed_at.isoformat(),
                    "heartbeat_at": claimed_at.isoformat(),
                }
            ),
        )
        primary_session.add(running_job)
        primary_session.commit()
        primary_session.refresh(running_job)

        stale_snapshot_payload_json = running_job.payload_json

        stolen_job = stealing_session.scalar(select(Job).where(Job.id == running_job.id))
        stolen_job.payload_json = json.dumps(
            {
                "source": "refresh-endpoint",
                "attempt_count": 0,
                "max_attempts": 3,
                "worker_id": "worker-b",
                "claimed_at": (claimed_at + timedelta(minutes=5)).isoformat(),
                "heartbeat_at": (claimed_at + timedelta(minutes=5)).isoformat(),
            }
        )
        stealing_session.commit()

        completion_result = apply_running_job_lease_update(
            primary_session,
            job_id=running_job.id,
            expected_payload_json=stale_snapshot_payload_json,
            next_status=JOB_STATUS_COMPLETED,
            next_payload_json=json.dumps(
                {
                    "source": "refresh-endpoint",
                    "items_seen": 1,
                    "auth_mode": "browser-assisted-apple-web",
                }
            ),
            error_message=None,
        )
        final_job = verification_session.scalar(select(Job).where(Job.id == running_job.id))
    finally:
        primary_session.close()
        stealing_session.close()
        verification_session.close()

    assert completion_result is None
    assert final_job is not None
    assert final_job.status == JOB_STATUS_RUNNING
    assert json.loads(final_job.payload_json or "{}")["worker_id"] == "worker-b"


def test_run_next_job_requeues_transient_failures_until_attempt_budget_is_exhausted(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        queued_job = enqueue_metadata_refresh(session)
        first_result = run_next_job(session, client=TransientFailureICloudWebClient())
        first_status = first_result.status
        first_error_message = first_result.error_message
        first_payload = json.loads(first_result.payload_json or "{}")

        second_result = run_next_job(session, client=TransientFailureICloudWebClient())
        second_status = second_result.status
        second_error_message = second_result.error_message
        second_payload = json.loads(second_result.payload_json or "{}")

        third_result = run_next_job(session, client=TransientFailureICloudWebClient())
        third_status = third_result.status
        third_error_message = third_result.error_message
        third_payload = json.loads(third_result.payload_json or "{}")
        final_stored_job = session.scalar(select(Job).where(Job.id == queued_job.id))
    finally:
        session.close()

    assert first_status == JOB_STATUS_QUEUED
    assert first_error_message is not None
    assert first_payload["attempt_count"] == 1
    assert first_payload["max_attempts"] == 3

    assert second_status == JOB_STATUS_QUEUED
    assert second_error_message is not None
    assert second_payload["attempt_count"] == 2
    assert second_payload["max_attempts"] == 3

    assert third_status == JOB_STATUS_FAILED
    assert third_error_message is not None
    assert third_payload["attempt_count"] == 3
    assert third_payload["max_attempts"] == 3
    assert final_stored_job is not None
    assert final_stored_job.status == JOB_STATUS_FAILED


def test_enqueue_metadata_refresh_coalesces_duplicate_queued_work(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        first_job = enqueue_metadata_refresh(session)
        second_job = enqueue_metadata_refresh(session)
        stored_jobs = session.scalars(select(Job).order_by(Job.id.asc())).all()
    finally:
        session.close()

    assert first_job.id == second_job.id
    assert len(stored_jobs) == 1
    assert stored_jobs[0].status == JOB_STATUS_QUEUED


def test_enqueue_metadata_refresh_uses_postgres_advisory_lock_for_coalescing():
    lock_calls: list[tuple[str, dict[str, object] | None]] = []

    class FakePostgresSession:
        def get_bind(self):
            return type(
                "FakeBind",
                (),
                {"dialect": type("FakeDialect", (), {"name": "postgresql"})()},
            )()

        def execute(self, statement, params=None):
            lock_calls.append((str(statement), params))
            return None

    job_runner_module._acquire_refresh_enqueue_lock(FakePostgresSession())

    assert lock_calls == [
        (
            "SELECT pg_advisory_xact_lock(:lock_key)",
            {"lock_key": job_runner_module.REFRESH_ENQUEUE_LOCK_KEY},
        )
    ]


def test_enqueue_metadata_refresh_returns_existing_job_after_active_refresh_unique_violation(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()
    original_commit = session.commit

    def racing_commit() -> None:
        competing_session = session_factory()
        try:
            competing_session.add(
                Job(
                    job_type=METADATA_REFRESH_JOB_TYPE,
                    status=JOB_STATUS_QUEUED,
                    payload_json=json.dumps(
                        {
                            "source": "refresh-endpoint",
                            "attempt_count": 0,
                            "max_attempts": 3,
                        }
                    ),
                )
            )
            competing_session.commit()
        finally:
            competing_session.close()
        raise IntegrityError("INSERT INTO jobs", {}, RuntimeError("unique violation"))

    monkeypatch.setattr(session, "commit", racing_commit)

    try:
        coalesced_job = enqueue_metadata_refresh(session)
        stored_jobs = session.scalars(select(Job).order_by(Job.id.asc())).all()
    finally:
        monkeypatch.setattr(session, "commit", original_commit)
        session.close()

    assert coalesced_job is not None
    assert len(stored_jobs) == 1
    assert coalesced_job.id == stored_jobs[0].id
    assert stored_jobs[0].status == JOB_STATUS_QUEUED


def test_request_refresh_coalesces_duplicate_running_work(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    session = session_factory()

    try:
        queued_job = enqueue_metadata_refresh(session)
        claimed_job = claim_next_metadata_refresh_job(session, worker_id="worker-a")
        response = request_refresh(session)
        stored_jobs = session.scalars(select(Job).order_by(Job.id.asc())).all()
    finally:
        session.close()

    assert claimed_job is not None
    assert claimed_job.id == queued_job.id
    assert response == {
        "status": "running",
        "job_id": queued_job.id,
        "job_type": METADATA_REFRESH_JOB_TYPE,
    }
    assert len(stored_jobs) == 1
    assert stored_jobs[0].status == JOB_STATUS_RUNNING


def test_worker_loop_polls_and_processes_refresh_jobs_enqueued_after_startup(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    sleep_calls: list[float] = []
    original_interval = job_runner_module.DEFAULT_BACKGROUND_REFRESH_INTERVAL_SECONDS
    job_runner_module.DEFAULT_BACKGROUND_REFRESH_INTERVAL_SECONDS = 0

    def fake_sleep(interval_seconds: float) -> None:
        sleep_calls.append(interval_seconds)
        session = session_factory()
        try:
            enqueue_metadata_refresh(session)
        finally:
            session.close()

    try:
        processed_count = run_worker_loop(
            session_factory=session_factory,
            client=FakeICloudWebClient(
                [
                    {
                        "id": "queued-after-startup",
                        "name": "Queued After Startup",
                        "path": "/Work/QueuedAfterStartup.md",
                        "extension": "md",
                        "contentType": "text/markdown",
                    }
                ]
            ),
            max_polls=2,
            poll_interval_seconds=0.25,
            sleep_fn=fake_sleep,
        )
    finally:
        job_runner_module.DEFAULT_BACKGROUND_REFRESH_INTERVAL_SECONDS = original_interval

    verification_session = session_factory()
    try:
        stored_jobs = verification_session.scalars(select(Job).order_by(Job.id.asc())).all()
    finally:
        verification_session.close()

    assert processed_count == 1
    assert sleep_calls == [0.25]
    assert len(stored_jobs) == 1
    assert stored_jobs[0].status == JOB_STATUS_COMPLETED


def test_run_worker_once_enqueues_background_refresh_when_due(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    monkeypatch.setenv("BACKGROUND_REFRESH_INTERVAL_SECONDS", "60")

    processed_count = worker_module.run_worker_once(
        session_factory=session_factory,
        worker_id="worker-a",
        client=FakeICloudWebClient(
            [
                {
                    "id": "background-file",
                    "name": "Background.txt",
                    "path": "/Work/Background.txt",
                    "extension": "txt",
                    "contentType": "text/plain",
                }
            ]
        ),
    )

    verification_session = session_factory()
    try:
        stored_jobs = verification_session.scalars(select(Job).order_by(Job.id.asc())).all()
    finally:
        verification_session.close()

    assert processed_count == 1
    assert len(stored_jobs) == 1
    assert stored_jobs[0].status == JOB_STATUS_COMPLETED
    assert json.loads(stored_jobs[0].payload_json or "{}")["source"] == "background-scan"


def test_worker_loop_treats_schema_and_db_startup_errors_as_retryable_idle_polls(
    monkeypatch,
    capsys,
):
    sleep_calls: list[float] = []
    run_sequence = iter(
        [
            SchemaNotReadyError("jobs table missing"),
            OperationalError("SELECT 1", {}, RuntimeError("db starting")),
            1,
        ]
    )

    def fake_run_worker_once(**kwargs):
        next_item = next(run_sequence)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(worker_module, "run_worker_once", fake_run_worker_once)

    processed_count = run_worker_loop(
        max_polls=3,
        poll_interval_seconds=0.5,
        sleep_fn=sleep_calls.append,
    )
    captured = capsys.readouterr()

    assert processed_count == 1
    assert sleep_calls == [0.5, 0.5]
    assert "SchemaNotReadyError" in captured.err
    assert "jobs table missing" in captured.err
    assert "OperationalError" in captured.err
