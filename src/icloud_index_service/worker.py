from __future__ import annotations

from icloud_index_service.db import get_session_factory
from icloud_index_service.services.job_runner import run_next_job


def run_worker_once() -> int:
    session = get_session_factory()()
    try:
        job = run_next_job(session)
    finally:
        session.close()
    return 0 if job is None else 1


def main() -> None:
    run_worker_once()


if __name__ == "__main__":
    main()
