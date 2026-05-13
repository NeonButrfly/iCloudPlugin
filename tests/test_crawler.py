from __future__ import annotations

import json
from pathlib import Path

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
    JOB_STATUS_QUEUED,
    METADATA_REFRESH_JOB_TYPE,
    enqueue_metadata_refresh,
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
