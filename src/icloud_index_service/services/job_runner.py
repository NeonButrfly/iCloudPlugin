from __future__ import annotations

import hashlib
import json
import weakref
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.job import Job
from icloud_index_service.services.crawler import normalize_remote_item
from icloud_index_service.services.extractor import extract_text_content
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
REQUIRED_REFRESH_JOB_INDEXES = {"jobs": ("uq_jobs_active_metadata_refresh",)}
DEFAULT_STALE_RUNNING_SECONDS = 300
CLAIMED_AT_FIELD = "claimed_at"
HEARTBEAT_AT_FIELD = "heartbeat_at"
WORKER_ID_FIELD = "worker_id"
ATTEMPT_COUNT_FIELD = "attempt_count"
MAX_ATTEMPTS_FIELD = "max_attempts"
DEFAULT_MAX_ATTEMPTS = 3
REFRESH_ENQUEUE_LOCK_KEY = 61001
_SCHEMA_READY_CACHE: weakref.WeakKeyDictionary[object, bool] = weakref.WeakKeyDictionary()


class SchemaNotReadyError(RuntimeError):
    pass


class LostLeaseError(RuntimeError):
    pass


def ensure_refresh_job_schema_ready(session: Session) -> None:
    bind = session.get_bind()
    if _SCHEMA_READY_CACHE.get(bind):
        return

    inspector = inspect(bind)
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
    missing_indexes = []
    for table_name, required_index_names in REQUIRED_REFRESH_JOB_INDEXES.items():
        existing_index_names = {
            index_definition["name"]
            for index_definition in inspector.get_indexes(table_name)
        }
        for required_index_name in required_index_names:
            if required_index_name not in existing_index_names:
                missing_indexes.append(f"{table_name}.{required_index_name}")
    if missing_indexes:
        missing_indexes_csv = ", ".join(missing_indexes)
        raise SchemaNotReadyError(
            "Refresh job schema is not ready; missing indexes: "
            f"{missing_indexes_csv}. Apply the latest follow-up migration before using "
            "/refresh or the worker."
        )
    _SCHEMA_READY_CACHE[bind] = True


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


def _acquire_refresh_enqueue_lock(session: Session) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": REFRESH_ENQUEUE_LOCK_KEY},
    )


def _find_existing_active_metadata_refresh_job(session: Session) -> Job | None:
    existing_job = session.scalar(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .where(Job.status == JOB_STATUS_RUNNING)
        .order_by(Job.id.asc())
        .limit(1)
    )
    if existing_job is not None:
        return existing_job
    return session.scalar(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .where(Job.status == JOB_STATUS_QUEUED)
        .order_by(Job.id.asc())
        .limit(1)
    )


def _coerce_content_bytes(raw_item: dict[str, object]) -> bytes | None:
    raw_bytes = raw_item.get("content_bytes")
    if isinstance(raw_bytes, bytes):
        return raw_bytes
    if isinstance(raw_bytes, bytearray):
        return bytes(raw_bytes)

    raw_text = raw_item.get("content_text")
    if isinstance(raw_text, str):
        return raw_text.encode("utf-8")
    return None


def _upsert_file_record(
    session: Session,
    *,
    normalized_item: dict[str, object],
) -> FileRecord:
    external_id = str(normalized_item["external_id"])
    file_record = session.scalar(
        select(FileRecord).where(FileRecord.external_id == external_id)
    )
    if file_record is None:
        file_record = FileRecord(
            external_id=external_id,
            name=str(normalized_item["name"]),
            path=str(normalized_item["path"]),
            mime_type=str(normalized_item["mime_type"]),
            size_bytes=(
                int(normalized_item["size_bytes"])
                if normalized_item.get("size_bytes") is not None
                else None
            ),
        )
        session.add(file_record)
        session.flush()
        return file_record

    file_record.name = str(normalized_item["name"])
    file_record.path = str(normalized_item["path"])
    file_record.mime_type = str(normalized_item["mime_type"])
    file_record.size_bytes = (
        int(normalized_item["size_bytes"])
        if normalized_item.get("size_bytes") is not None
        else None
    )
    file_record.is_deleted = False
    session.flush()
    return file_record


def _persist_refresh_results(
    session: Session,
    *,
    raw_items: list[dict[str, object]],
    normalized_items: list[dict[str, object]],
) -> list[dict[str, str]]:
    extraction_failures: list[dict[str, str]] = []

    for raw_item, normalized_item in zip(raw_items, normalized_items, strict=True):
        file_record = _upsert_file_record(session, normalized_item=normalized_item)
        extracted_content = session.scalar(
            select(ExtractedContent).where(ExtractedContent.file_id == file_record.id)
        )
        payload = _coerce_content_bytes(raw_item)
        if payload is None:
            if extracted_content is not None:
                session.delete(extracted_content)
                session.flush()
            continue

        try:
            extracted_text = extract_text_content(
                path=file_record.path,
                mime_type=file_record.mime_type,
                payload=payload,
            )
        except Exception as exc:
            extraction_failures.append(
                {
                    "external_id": file_record.external_id,
                    "path": file_record.path,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if not extracted_text:
            if extracted_content is not None:
                session.delete(extracted_content)
                session.flush()
            continue

        content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()
        if extracted_content is None:
            extracted_content = ExtractedContent(
                file_id=file_record.id,
                content_text=extracted_text,
                content_hash=content_hash,
            )
            session.add(extracted_content)
        else:
            extracted_content.content_text = extracted_text
            extracted_content.content_hash = content_hash
        session.flush()

    return extraction_failures


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
    _acquire_refresh_enqueue_lock(session)
    existing_job = _find_existing_active_metadata_refresh_job(session)
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
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing_job = _find_existing_active_metadata_refresh_job(session)
        if existing_job is not None:
            return existing_job
        raise
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
        raw_items = active_client.list_drive_items(heartbeat=heartbeat)
        items = [normalize_remote_item(item) for item in raw_items]
        extraction_failures = _persist_refresh_results(
            session,
            raw_items=raw_items,
            normalized_items=items,
        )
        payload = _deserialize_payload(lease_payload_json)
        payload.pop(CLAIMED_AT_FIELD, None)
        payload.pop(HEARTBEAT_AT_FIELD, None)
        payload.pop(WORKER_ID_FIELD, None)
        payload.pop(ATTEMPT_COUNT_FIELD, None)
        payload.pop(MAX_ATTEMPTS_FIELD, None)
        payload["source"] = "refresh-endpoint"
        payload["items_seen"] = len(items)
        payload["auth_mode"] = active_client.auth_mode
        if extraction_failures:
            payload["extraction_failures"] = extraction_failures
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
        session.rollback()
        return None
    except Exception as exc:
        session.rollback()
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
