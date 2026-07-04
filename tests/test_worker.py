from __future__ import annotations

import icloud_index_service.worker as worker_module


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_run_worker_once_drains_cloud_vault_tasks_after_refresh_poll(monkeypatch):
    calls: list[str] = []
    fake_session = _FakeSession()

    monkeypatch.setattr(worker_module, "get_session_factory", lambda: (lambda: fake_session))
    monkeypatch.setattr(
        worker_module,
        "maybe_enqueue_background_refresh",
        lambda session: calls.append("enqueue-refresh"),
    )
    monkeypatch.setattr(
        worker_module,
        "run_next_job",
        lambda session, *, client=None, worker_id=None: calls.append("run-refresh-job") or None,
    )
    monkeypatch.setattr(
        worker_module,
        "continue_cloud_vault_task_queue",
        lambda session, *, limit: calls.append(f"drain-tasks:{limit}") or {"processed_count": 2},
    )

    processed_count = worker_module.run_worker_once(worker_id="worker-1")

    assert processed_count == 2
    assert calls == ["enqueue-refresh", "run-refresh-job", "drain-tasks:1"]
    assert fake_session.closed is True
