from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from icloud_index_service.api.refresh import request_refresh
from icloud_index_service.models.base import Base
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
    claim_next_metadata_refresh_job,
    enqueue_metadata_refresh,
    recover_stale_running_jobs,
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


class FakeICloudWebClient(ICloudWebClient):
    def __init__(self, remote_items: list[dict[str, object]]) -> None:
        super().__init__(auth_mode="browser-assisted-apple-web")
        self._remote_items = remote_items

    def list_drive_items(self) -> list[dict[str, object]]:
        return list(self._remote_items)


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
    assert reloaded_job.error_message is not None
    assert "stale running job" in reloaded_job.error_message.lower()


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


def test_worker_loop_polls_and_processes_refresh_jobs_enqueued_after_startup(tmp_path):
    session_factory = _build_session_factory(tmp_path, create_schema=True)
    sleep_calls: list[float] = []

    def fake_sleep(interval_seconds: float) -> None:
        sleep_calls.append(interval_seconds)
        session = session_factory()
        try:
            enqueue_metadata_refresh(session)
        finally:
            session.close()

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

    verification_session = session_factory()
    try:
        stored_jobs = verification_session.scalars(select(Job).order_by(Job.id.asc())).all()
    finally:
        verification_session.close()

    assert processed_count == 1
    assert sleep_calls == [0.25]
    assert len(stored_jobs) == 1
    assert stored_jobs[0].status == JOB_STATUS_COMPLETED
