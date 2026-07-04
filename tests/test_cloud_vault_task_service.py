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
