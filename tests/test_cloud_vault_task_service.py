from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from icloud_index_service.models.base import Base
from icloud_index_service.models.cloud_vault_task import CloudVaultTask
from icloud_index_service.services import cloud_vault_task_service as service


def test_continue_cloud_vault_task_rolls_back_and_marks_failed_after_dispatch_error(tmp_path, monkeypatch):
    database_path = tmp_path / "cloud-vault-task-service.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = CloudVaultTask(
            task_id="task-1",
            task_type=service.TASK_TYPE_DEDUPE_ANALYSIS,
            status=service.TASK_STATUS_QUEUED,
            input_json="{}",
            progress_json="{}",
            priority=100,
        )
        session.add(task)
        session.commit()

        def boom(session, *, task):
            session.execute(text("select * from definitely_missing_table"))
            raise AssertionError("unreachable")

        monkeypatch.setattr(service, "_dispatch_task", boom)

        payload = service.continue_cloud_vault_task(session, task_id="task-1")

    assert payload["status"] == service.TASK_STATUS_FAILED
    assert "definitely_missing_table" in str(payload["error"] or payload["message"])


def test_continue_cloud_vault_task_clears_stale_failure_metadata_when_reopened(tmp_path, monkeypatch):
    database_path = tmp_path / "cloud-vault-task-service.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = CloudVaultTask(
            task_id="task-2",
            task_type=service.TASK_TYPE_DEDUPE_ANALYSIS,
            status=service.TASK_STATUS_FAILED,
            input_json="{}",
            progress_json="{}",
            result_json='{"job":{"processed_count":10}}',
            error_message="old overflow",
            priority=100,
        )
        session.add(task)
        session.commit()
        task.completed_at = service._utc_now()
        session.commit()

        def keep_running(session, *, task):
            task.progress_json = '{"dedupe_job_id":"job-1","dedupe_status":"running","groups_found":1}'
            task.result_json = '{"job":{"processed_count":11}}'
            session.commit()
            return {"job": {"processed_count": 11}}

        monkeypatch.setattr(service, "_dispatch_task", keep_running)

        payload = service.continue_cloud_vault_task(session, task_id="task-2")
        refreshed = session.get(CloudVaultTask, task.id)

    assert payload["status"] == service.TASK_STATUS_RUNNING
    assert payload["error"] is None
    assert payload["completed_at"] is None
    assert refreshed is not None
    assert refreshed.error_message is None
    assert refreshed.completed_at is None
