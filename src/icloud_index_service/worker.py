from __future__ import annotations

import os
import time

from icloud_index_service.db import get_session_factory
from icloud_index_service.services.job_runner import run_next_job

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


def run_worker_once(*, session_factory=None) -> int:
    active_session_factory = session_factory or get_session_factory()
    session = active_session_factory()
    try:
        job = run_next_job(session)
    finally:
        session.close()
    return 0 if job is None else 1


def run_worker_loop(
    *,
    session_factory=None,
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
        processed_this_poll = run_worker_once(session_factory=session_factory)
        processed_count += processed_this_poll
        if processed_this_poll == 0 and (max_polls is None or poll_count < max_polls):
            sleep_fn(active_interval)

    return processed_count


def main() -> None:
    run_worker_loop()


if __name__ == "__main__":
    main()
