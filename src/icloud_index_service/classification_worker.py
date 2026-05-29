from __future__ import annotations

import os
import sys
import time

from sqlalchemy.exc import OperationalError

from icloud_index_service.db import get_session_factory
from icloud_index_service.services.classification_submission import (
    ClassifierSubmissionNotReadyError,
    enqueue_classification_backfill,
    enqueue_targeted_reclassification_from_manual_feedback,
    get_classification_submission_concurrency,
    get_classification_targeted_requeue_limit,
    get_classification_submission_enabled,
    get_classification_submission_poll_interval_seconds,
    run_next_classification_job,
)
from icloud_index_service.services.vault_reconciliation import (
    run_vault_reconciliation_once,
)


def get_classification_worker_identity() -> str:
    hostname = os.getenv("HOSTNAME") or os.getenv("COMPUTERNAME") or "classification-worker"
    return f"{hostname}:{os.getpid()}"


def run_classification_worker_once(
    *,
    session_factory=None,
    worker_id: str | None = None,
    client=None,
) -> int:
    if not get_classification_submission_enabled():
        return 0

    active_session_factory = session_factory or get_session_factory()
    concurrency = get_classification_submission_concurrency()
    processed_count = 0

    seed_session = active_session_factory()
    try:
        enqueue_classification_backfill(seed_session, limit=max(concurrency * 2, concurrency))
        enqueue_targeted_reclassification_from_manual_feedback(
            seed_session,
            limit=get_classification_targeted_requeue_limit(),
        )
    finally:
        seed_session.close()

    for _ in range(concurrency):
        session = active_session_factory()
        try:
            job = run_next_classification_job(
                session,
                client=client,
                worker_id=worker_id or get_classification_worker_identity(),
            )
        finally:
            session.close()
        if job is None:
            break
        processed_count += 1

    reconciliation_session = active_session_factory()
    try:
        run_vault_reconciliation_once(reconciliation_session)
    finally:
        reconciliation_session.close()

    return processed_count


def run_classification_worker_loop(
    *,
    session_factory=None,
    worker_id: str | None = None,
    client=None,
    max_polls: int | None = None,
    poll_interval_seconds: float | None = None,
    sleep_fn=time.sleep,
) -> int:
    active_interval = (
        get_classification_submission_poll_interval_seconds()
        if poll_interval_seconds is None
        else poll_interval_seconds
    )
    processed_count = 0
    poll_count = 0

    while max_polls is None or poll_count < max_polls:
        poll_count += 1
        try:
            processed_this_poll = run_classification_worker_once(
                session_factory=session_factory,
                worker_id=worker_id,
                client=client,
            )
        except (ClassifierSubmissionNotReadyError, OperationalError) as exc:
            print(
                (
                    "[classification-worker] Retrying after startup dependency error "
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
    run_classification_worker_loop()


if __name__ == "__main__":
    main()
