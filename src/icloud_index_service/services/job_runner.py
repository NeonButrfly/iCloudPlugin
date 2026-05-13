from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session

from icloud_index_service.models.job import Job
from icloud_index_service.services.crawler import crawl_metadata
from icloud_index_service.services.icloud_web_client import (
    ICloudWebClient,
    ICloudWebClientNotReadyError,
    create_icloud_web_client,
)

METADATA_REFRESH_JOB_TYPE = "metadata-refresh"
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
REQUIRED_REFRESH_JOB_TABLES = ("jobs", "sync_runs")
DEFAULT_STALE_RUNNING_SECONDS = 300
CLAIMED_AT_FIELD = "claimed_at"
HEARTBEAT_AT_FIELD = "heartbeat_at"
WORKER_ID_FIELD = "worker_id"
ATTEMPT_COUNT_FIELD = "attempt_count"
MAX_ATTEMPTS_FIELD = "max_attempts"
DEFAULT_MAX_ATTEMPTS = 3


class SchemaNotReadyError(RuntimeError):
    pass


class LostLeaseError(RuntimeError):
    pass


def ensure_refresh_job_schema_ready(session: Session) -> None:
    inspector = inspect(session.get_bind())
    missing_tables = [
        table_name
        for table_name in REQUIRED_REFRESH_JOB_TABLES
        if not inspector.has_table(table_name)
    ]
    if missing_tables:
        missing_tables_csv = ", ".join(missing_tables)
        raise SchemaNotReadyError(
            "Refresh job schema is not ready; missing tables: "
            f"{missing_tables_csv}. Run migrations before using /refresh or the worker."
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _deserialize_payload(payload_json: str | None) -> dict[str, object]:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _serialize_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload)


def _parse_iso_timestamp(raw_value: object) -> datetime | None:
    if not isinstance(raw_value, str):
        return None
    try:
        parsed_value = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    if parsed_value.tzinfo is None:
        return parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value.astimezone(timezone.utc)


def _parse_claimed_at(payload: dict[str, object]) -> datetime | None:
    return _parse_iso_timestamp(payload.get(CLAIMED_AT_FIELD))


def _parse_heartbeat_at(payload: dict[str, object]) -> datetime | None:
    return _parse_iso_timestamp(payload.get(HEARTBEAT_AT_FIELD))


def _parse_attempt_count(payload: dict[str, object]) -> int:
    raw_attempt_count = payload.get(ATTEMPT_COUNT_FIELD, 0)
    if isinstance(raw_attempt_count, bool):
        return 0
    if isinstance(raw_attempt_count, int):
        return max(raw_attempt_count, 0)
    return 0


def _parse_max_attempts(payload: dict[str, object]) -> int:
    raw_max_attempts = payload.get(MAX_ATTEMPTS_FIELD, DEFAULT_MAX_ATTEMPTS)
    if isinstance(raw_max_attempts, bool):
        return DEFAULT_MAX_ATTEMPTS
    if isinstance(raw_max_attempts, int) and raw_max_attempts > 0:
        return raw_max_attempts
    return DEFAULT_MAX_ATTEMPTS


def renew_refresh_job_heartbeat(
    session: Session,
    job_id: int,
    *,
    expected_payload_json: str | None = None,
    now: datetime | None = None,
) -> Job | None:
    ensure_refresh_job_schema_ready(session)
    job = session.get(Job, job_id)
    if job is None or job.job_type != METADATA_REFRESH_JOB_TYPE or job.status != JOB_STATUS_RUNNING:
        return None

    snapshot_payload_json = expected_payload_json or job.payload_json
    payload = _deserialize_payload(snapshot_payload_json)
    payload[HEARTBEAT_AT_FIELD] = (now or _utc_now()).isoformat()
    return apply_running_job_lease_update(
        session,
        job_id=job_id,
        expected_payload_json=snapshot_payload_json,
        next_status=JOB_STATUS_RUNNING,
        next_payload_json=_serialize_payload(payload),
        error_message=job.error_message,
    )


def apply_running_job_lease_update(
    session: Session,
    *,
    job_id: int,
    expected_payload_json: str | None,
    next_status: str,
    next_payload_json: str,
    error_message: str | None,
) -> Job | None:
    ensure_refresh_job_schema_ready(session)
    update_result = session.execute(
        update(Job)
        .where(Job.id == job_id)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .where(Job.status == JOB_STATUS_RUNNING)
        .where(Job.payload_json == expected_payload_json)
        .values(
            status=next_status,
            payload_json=next_payload_json,
            error_message=error_message,
        )
    )
    if update_result.rowcount == 0:
        session.rollback()
        return None

    session.commit()
    session.expire_all()
    return session.get(Job, job_id)


def apply_stale_recovery_update(
    session: Session,
    *,
    job_id: int,
    expected_payload_json: str | None,
    next_status: str,
    next_payload_json: str,
    error_message: str,
) -> bool:
    return (
        apply_running_job_lease_update(
            session,
            job_id=job_id,
            expected_payload_json=expected_payload_json,
            next_status=next_status,
            next_payload_json=next_payload_json,
            error_message=error_message,
        )
        is not None
    )


def recover_stale_running_jobs(
    session: Session,
    *,
    stale_after_seconds: int = DEFAULT_STALE_RUNNING_SECONDS,
    now: datetime | None = None,
) -> int:
    ensure_refresh_job_schema_ready(session)
    current_time = now or _utc_now()
    stale_cutoff = current_time - timedelta(seconds=stale_after_seconds)
    recovered_count = 0

    running_jobs = session.scalars(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .where(Job.status == JOB_STATUS_RUNNING)
        .order_by(Job.id.asc())
    ).all()

    for job in running_jobs:
        payload = _deserialize_payload(job.payload_json)
        snapshot_payload_json = job.payload_json
        claimed_at = _parse_claimed_at(payload)
        if claimed_at is None:
            if apply_stale_recovery_update(
                session,
                job_id=job.id,
                expected_payload_json=snapshot_payload_json,
                next_status=JOB_STATUS_FAILED,
                next_payload_json=_serialize_payload(payload),
                error_message=(
                    "Failed running refresh job with missing or invalid claimed_at lease "
                    "metadata so it does not stay wedged or duplicate active work."
                ),
            ):
                recovered_count += 1
            continue

        heartbeat_at = _parse_heartbeat_at(payload) or claimed_at
        if heartbeat_at > stale_cutoff:
            continue

        attempt_count = _parse_attempt_count(payload) + 1
        max_attempts = _parse_max_attempts(payload)
        payload.pop(CLAIMED_AT_FIELD, None)
        payload.pop(HEARTBEAT_AT_FIELD, None)
        payload.pop(WORKER_ID_FIELD, None)
        payload[ATTEMPT_COUNT_FIELD] = attempt_count
        payload[MAX_ATTEMPTS_FIELD] = max_attempts

        if attempt_count < max_attempts:
            next_status = JOB_STATUS_QUEUED
            error_message = (
                "Recovered stale running job so it can be retried by the worker "
                f"({attempt_count}/{max_attempts})."
            )
        else:
            next_status = JOB_STATUS_FAILED
            error_message = (
                "Refresh job exhausted retry budget during stale-running recovery "
                f"({attempt_count}/{max_attempts})."
            )

        if apply_stale_recovery_update(
            session,
            job_id=job.id,
            expected_payload_json=snapshot_payload_json,
            next_status=next_status,
            next_payload_json=_serialize_payload(payload),
            error_message=error_message,
        ):
            recovered_count += 1

    return recovered_count


def claim_next_metadata_refresh_job(
    session: Session,
    *,
    worker_id: str | None = None,
    now: datetime | None = None,
) -> Job | None:
    ensure_refresh_job_schema_ready(session)
    claimed_at = now or _utc_now()

    while True:
        queued_job_id = session.scalar(
            select(Job.id)
            .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
            .where(Job.status == JOB_STATUS_QUEUED)
            .order_by(Job.id.asc())
            .limit(1)
        )
        if queued_job_id is None:
            return None

        queued_job = session.get(Job, queued_job_id)
        if queued_job is None:
            return None

        payload = _deserialize_payload(queued_job.payload_json)
        payload[ATTEMPT_COUNT_FIELD] = _parse_attempt_count(payload)
        payload[MAX_ATTEMPTS_FIELD] = _parse_max_attempts(payload)
        payload[CLAIMED_AT_FIELD] = claimed_at.isoformat()
        payload[HEARTBEAT_AT_FIELD] = claimed_at.isoformat()
        if worker_id is not None:
            payload[WORKER_ID_FIELD] = worker_id

        claim_result = session.execute(
            update(Job)
            .where(Job.id == queued_job_id)
            .where(Job.status == JOB_STATUS_QUEUED)
            .values(
                status=JOB_STATUS_RUNNING,
                payload_json=_serialize_payload(payload),
                error_message=None,
            )
        )
        if claim_result.rowcount == 0:
            session.rollback()
            continue

        session.commit()
        return session.get(Job, queued_job_id)


def enqueue_metadata_refresh(session: Session) -> Job:
    ensure_refresh_job_schema_ready(session)
    existing_job = session.scalar(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .where(Job.status == JOB_STATUS_RUNNING)
        .order_by(Job.id.asc())
        .limit(1)
    )
    if existing_job is None:
        existing_job = session.scalar(
            select(Job)
            .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
            .where(Job.status == JOB_STATUS_QUEUED)
            .order_by(Job.id.asc())
            .limit(1)
        )
    if existing_job is not None:
        return existing_job

    job = Job(
        job_type=METADATA_REFRESH_JOB_TYPE,
        status=JOB_STATUS_QUEUED,
        payload_json=json.dumps(
            {
                "source": "refresh-endpoint",
                ATTEMPT_COUNT_FIELD: 0,
                MAX_ATTEMPTS_FIELD: DEFAULT_MAX_ATTEMPTS,
            }
        ),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def run_next_job(
    session: Session,
    client: ICloudWebClient | None = None,
    worker_id: str | None = None,
    stale_after_seconds: int = DEFAULT_STALE_RUNNING_SECONDS,
    now: datetime | None = None,
) -> Job | None:
    ensure_refresh_job_schema_ready(session)
    recover_stale_running_jobs(
        session,
        stale_after_seconds=stale_after_seconds,
        now=now,
    )
    job = claim_next_metadata_refresh_job(
        session,
        worker_id=worker_id,
        now=now,
    )
    if job is None:
        return None

    active_client = client or create_icloud_web_client()
    lease_payload_json = job.payload_json

    def heartbeat() -> None:
        nonlocal lease_payload_json
        renewed_job = renew_refresh_job_heartbeat(
            session,
            job.id,
            expected_payload_json=lease_payload_json,
        )
        if renewed_job is None:
            raise LostLeaseError(
                "Refresh job lease was lost during crawl heartbeat; aborting stale worker."
            )
        lease_payload_json = renewed_job.payload_json

    try:
        items = crawl_metadata(active_client, heartbeat=heartbeat)
        payload = _deserialize_payload(lease_payload_json)
        payload.pop(CLAIMED_AT_FIELD, None)
        payload.pop(HEARTBEAT_AT_FIELD, None)
        payload.pop(WORKER_ID_FIELD, None)
        payload.pop(ATTEMPT_COUNT_FIELD, None)
        payload.pop(MAX_ATTEMPTS_FIELD, None)
        payload["source"] = "refresh-endpoint"
        payload["items_seen"] = len(items)
        payload["auth_mode"] = active_client.auth_mode
        completed_job = apply_running_job_lease_update(
            session,
            job_id=job.id,
            expected_payload_json=lease_payload_json,
            next_status=JOB_STATUS_COMPLETED,
            next_payload_json=_serialize_payload(payload),
            error_message=None,
        )
        return completed_job
    except LostLeaseError:
        return None
    except Exception as exc:
        payload = _deserialize_payload(lease_payload_json)
        attempt_count = _parse_attempt_count(payload) + 1
        max_attempts = _parse_max_attempts(payload)

        payload.pop(CLAIMED_AT_FIELD, None)
        payload.pop(HEARTBEAT_AT_FIELD, None)
        payload.pop(WORKER_ID_FIELD, None)
        payload[ATTEMPT_COUNT_FIELD] = attempt_count
        payload[MAX_ATTEMPTS_FIELD] = max_attempts
        next_payload_json = _serialize_payload(payload)

        if isinstance(exc, ICloudWebClientNotReadyError):
            next_status = JOB_STATUS_FAILED
            error_message = f"{type(exc).__name__}: {exc}"
        elif attempt_count < max_attempts:
            next_status = JOB_STATUS_QUEUED
            error_message = (
                f"Retrying refresh job after transient crawl failure "
                f"({attempt_count}/{max_attempts}): {type(exc).__name__}: {exc}"
            )
        else:
            next_status = JOB_STATUS_FAILED
            error_message = (
                f"Refresh job exhausted retry budget "
                f"({attempt_count}/{max_attempts}): {type(exc).__name__}: {exc}"
            )
        return apply_running_job_lease_update(
            session,
            job_id=job.id,
            expected_payload_json=lease_payload_json,
            next_status=next_status,
            next_payload_json=next_payload_json,
            error_message=error_message,
        )
