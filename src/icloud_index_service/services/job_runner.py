from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from icloud_index_service.models.job import Job
from icloud_index_service.services.crawler import crawl_metadata
from icloud_index_service.services.icloud_web_client import (
    ICloudWebClient,
    create_icloud_web_client,
)

METADATA_REFRESH_JOB_TYPE = "metadata-refresh"
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


def enqueue_metadata_refresh(session: Session) -> Job:
    job = Job(
        job_type=METADATA_REFRESH_JOB_TYPE,
        status=JOB_STATUS_QUEUED,
        payload_json=json.dumps({"source": "refresh-endpoint"}),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def run_next_job(
    session: Session,
    client: ICloudWebClient | None = None,
) -> Job | None:
    job = session.scalar(
        select(Job)
        .where(Job.status == JOB_STATUS_QUEUED)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .order_by(Job.id.asc())
        .limit(1)
    )
    if job is None:
        return None

    job.status = JOB_STATUS_RUNNING
    session.commit()

    active_client = client or create_icloud_web_client()
    try:
        items = crawl_metadata(active_client)
        job.status = JOB_STATUS_COMPLETED
        job.payload_json = json.dumps(
            {
                "source": "refresh-endpoint",
                "items_seen": len(items),
                "auth_mode": active_client.auth_mode,
            }
        )
        job.error_message = None
    except Exception as exc:
        job.status = JOB_STATUS_FAILED
        job.error_message = f"{type(exc).__name__}: {exc}"

    session.commit()
    session.refresh(job)
    return job
