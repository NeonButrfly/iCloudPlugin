from __future__ import annotations

import os
import sys
import time

from icloud_index_service.db import get_session_factory
from icloud_index_service.services.cloud_vault_task_service import (
    continue_cloud_vault_task_queue,
    get_cloud_vault_task_worker_enabled,
    get_cloud_vault_task_worker_limit,
)
from icloud_index_service.services.icloud_web_client import ICloudWebClient
from icloud_index_service.services.job_runner import (
    SchemaNotReadyError,
    maybe_enqueue_background_refresh,
    run_next_job,
)
from sqlalchemy.exc import OperationalError

DEFAULT_WORKER_POLL_INTERVAL_SECONDS = 5.0


def get_worker_poll_interval_seconds() -> float:
    raw_value = os.getenv("WORKER_POLL_INTERVAL_SECONDS")
    if raw_value is None:
        return DEFAULT_WORKER_POLL_INTERVAL_SECONDS
    try:
        poll_interval_seconds = float(raw_value)
    except ValueError:
        return DEFAULT_WORKER_POLL_INTERVAL_SECONDS
    if poll_interval_seconds <= 0:
        return DEFAULT_WORKER_POLL_INTERVAL_SECONDS
    return poll_interval_seconds


def get_worker_identity() -> str:
    hostname = os.getenv("HOSTNAME") or os.getenv("COMPUTERNAME") or "worker"
    return f"{hostname}:{os.getpid()}"


def run_worker_once(
    *,
    session_factory=None,
    worker_id: str | None = None,
    client: ICloudWebClient | None = None,
) -> int:
    active_session_factory = session_factory or get_session_factory()
    session = active_session_factory()
    try:
        maybe_enqueue_background_refresh(session)
        job = run_next_job(
            session,
            client=client,
            worker_id=worker_id or get_worker_identity(),
        )
        task_results = {"processed_count": 0}
        if get_cloud_vault_task_worker_enabled():
            task_results = continue_cloud_vault_task_queue(
                session,
                limit=get_cloud_vault_task_worker_limit(),
            )
    finally:
        session.close()
    return (0 if job is None else 1) + int(task_results.get("processed_count") or 0)


def run_worker_loop(
    *,
    session_factory=None,
    worker_id: str | None = None,
    client: ICloudWebClient | None = None,
    max_polls: int | None = None,
    poll_interval_seconds: float | None = None,
    sleep_fn=time.sleep,
) -> int:
    processed_count = 0
    poll_count = 0
    active_interval = (
        get_worker_poll_interval_seconds()
        if poll_interval_seconds is None
        else poll_interval_seconds
    )

    while max_polls is None or poll_count < max_polls:
        poll_count += 1
        try:
            processed_this_poll = run_worker_once(
                session_factory=session_factory,
                worker_id=worker_id,
                client=client,
            )
        except (SchemaNotReadyError, OperationalError) as exc:
            print(
                (
                    "[worker] Retrying after startup dependency error "
                    f"on poll {poll_count}: {type(exc).__name__}: {exc}"
                ),
                file=sys.stderr,
                flush=True,
            )
            processed_this_poll = 0
        processed_count += processed_this_poll
        if processed_this_poll == 0 and (max_polls is None or poll_count < max_polls):
            sleep_fn(active_interval)

    return processed_count


def main() -> None:
    run_worker_loop()


if __name__ == "__main__":
    main()
