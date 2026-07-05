from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from icloud_index_service.models.base import Base
from icloud_index_service.models.cloud_vault_task import CloudVaultTask
from icloud_index_service.models.file import FileRecord
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


def test_continue_search_note_task_completes_with_partial_failed_summary_and_reindexs_existing(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "cloud-vault-task-service.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        file_ids: list[int] = []
        for index in range(1, 6):
            file_record = FileRecord(
                external_id=f"file-{index}",
                name=f"File-{index}.pdf",
                path=f"/icloud/File-{index}.pdf",
                mime_type="application/pdf",
                extension="pdf",
            )
            session.add(file_record)
            session.flush()
            file_ids.append(file_record.id)

        task = CloudVaultTask(
            task_id="task-search-1",
            task_type=service.TASK_TYPE_SEARCH_NOTES,
            status=service.TASK_STATUS_QUEUED,
            input_json='{"index_after_create": true, "batch_size": 10}',
            progress_json=service._dumps({"matched_file_ids": file_ids, "cursor": 0, "results": []}),
            priority=100,
        )
        session.add(task)
        session.commit()

        reindex_calls: list[str | None] = []

        def fake_create(**kwargs):
            file_id = int(kwargs["file_id"])
            if file_id == file_ids[0]:
                return {"status": "created", "file_id": file_id, "note_path": str(tmp_path / "created.md")}
            if file_id == file_ids[1]:
                return {"status": "existing", "file_id": file_id, "note_path": str(tmp_path / "existing.md")}
            if file_id == file_ids[2]:
                return {"status": "unsupported", "file_id": file_id, "note_path": None, "message": "unsupported"}
            if file_id == file_ids[3]:
                return {"status": "blocked", "file_id": file_id, "note_path": None, "message": "blocked"}
            raise RuntimeError("duplicate key value violates unique constraint")

        def fake_reindex(session_arg, *, path_scope=None, limit=200):
            reindex_calls.append(path_scope)
            return {"status": "ok", "indexed": 1, "path_scope": path_scope, "limit": limit}

        monkeypatch.setattr(service, "create_document_vault_note", fake_create)
        monkeypatch.setattr(service, "reindex_document_vault_notes", fake_reindex)

        payload = service.continue_cloud_vault_task(session, task_id="task-search-1")
        refreshed = session.get(CloudVaultTask, task.id)

    assert payload["status"] == service.TASK_STATUS_COMPLETED
    assert payload["result"]["status"] == "partial_failed"
    assert payload["result"]["count_created"] == 1
    assert payload["result"]["count_existing"] == 1
    assert payload["result"]["count_skipped"] == 0
    assert payload["result"]["count_unsupported"] == 1
    assert payload["result"]["count_blocked"] == 1
    assert payload["result"]["count_failed"] == 1
    assert payload["result"]["processed_count"] == 5
    assert len(payload["result"]["results"]) == 5
    assert refreshed is not None
    assert service._loads_object(refreshed.progress_json)["cursor"] == 5
    assert len(reindex_calls) == 2
