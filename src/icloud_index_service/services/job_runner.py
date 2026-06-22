from __future__ import annotations

import hashlib
import json
import os
import weakref
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import inspect, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.job import Job
from icloud_index_service.models.sync_run import SyncRun
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
JOB_STATUS_PAUSED = "paused"
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
DEFAULT_REFRESH_BATCH_FILE_LIMIT = 100
DEFAULT_BACKGROUND_REFRESH_INTERVAL_SECONDS = 1800
DEFAULT_REFRESH_PROGRESS_HEARTBEAT_SECONDS = 10
DEFAULT_REFRESH_PROGRESS_HEARTBEAT_ITEMS = 10
_SCHEMA_READY_CACHE: weakref.WeakKeyDictionary[object, bool] = weakref.WeakKeyDictionary()
FRONTIER_FIELD = "frontier"
ITEMS_SEEN_FIELD = "items_seen"
BATCH_COUNT_FIELD = "batch_count"
BATCH_FILE_LIMIT_FIELD = "batch_file_limit"
BATCH_STAGE_FIELD = "batch_stage"
BATCH_STARTED_AT_FIELD = "batch_started_at"
LAST_PROGRESS_AT_FIELD = "last_progress_at"
CURRENT_BATCH_SIZE_FIELD = "current_batch_size"
CURRENT_BATCH_ITEMS_PROCESSED_FIELD = "current_batch_items_processed"
LAST_BATCH_COMPLETED_AT_FIELD = "last_batch_completed_at"
LAST_BATCH_SIZE_FIELD = "last_batch_size"
LAST_BATCH_DURATION_SECONDS_FIELD = "last_batch_duration_seconds"
BACKGROUND_REFRESH_SOURCE = "background-scan"
DEFAULT_REFRESH_CONTROL_PATH = ".runtime/refresh-control.json"


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


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_refresh_control_path() -> Path:
    configured_path = (os.getenv("ICLOUD_REFRESH_CONTROL_PATH") or "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    return _resolve_repo_root() / DEFAULT_REFRESH_CONTROL_PATH


def _read_refresh_control_state() -> dict[str, object]:
    control_path = _resolve_refresh_control_path()
    default_state: dict[str, object] = {
        "paused": False,
        "updated_at": None,
        "reason": None,
        "control_path": str(control_path),
    }
    if not control_path.is_file():
        return default_state
    try:
        payload = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            **default_state,
            "error": "refresh-control-invalid",
        }
    if not isinstance(payload, dict):
        return {
            **default_state,
            "error": "refresh-control-non-object",
        }
    return {
        **default_state,
        "paused": bool(payload.get("paused")),
        "updated_at": payload.get("updated_at"),
        "reason": payload.get("reason"),
    }


def _write_refresh_control_state(
    *,
    paused: bool,
    now: datetime | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    control_path = _resolve_refresh_control_path()
    control_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "paused": paused,
        "updated_at": (now or _utc_now()).isoformat(),
        "reason": reason,
    }
    control_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        **payload,
        "control_path": str(control_path),
    }


def is_background_refresh_paused() -> bool:
    return bool(_read_refresh_control_state().get("paused"))


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


def _coerce_utc_datetime(raw_value: datetime | None) -> datetime | None:
    if raw_value is None:
        return None
    if raw_value.tzinfo is None:
        return raw_value.replace(tzinfo=timezone.utc)
    return raw_value.astimezone(timezone.utc)


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


def get_refresh_batch_file_limit() -> int:
    raw_value = os.getenv("ICLOUD_REFRESH_BATCH_FILE_LIMIT")
    if raw_value is None:
        return DEFAULT_REFRESH_BATCH_FILE_LIMIT
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_REFRESH_BATCH_FILE_LIMIT
    return max(parsed_value, 1)


def get_background_refresh_interval_seconds() -> int:
    raw_value = os.getenv("BACKGROUND_REFRESH_INTERVAL_SECONDS")
    if raw_value is None:
        return DEFAULT_BACKGROUND_REFRESH_INTERVAL_SECONDS
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_BACKGROUND_REFRESH_INTERVAL_SECONDS
    return max(parsed_value, 0)


def get_refresh_progress_heartbeat_seconds() -> int:
    raw_value = os.getenv("ICLOUD_REFRESH_PROGRESS_HEARTBEAT_SECONDS")
    if raw_value is None:
        return DEFAULT_REFRESH_PROGRESS_HEARTBEAT_SECONDS
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_REFRESH_PROGRESS_HEARTBEAT_SECONDS
    return max(parsed_value, 1)


def get_refresh_progress_heartbeat_items() -> int:
    raw_value = os.getenv("ICLOUD_REFRESH_PROGRESS_HEARTBEAT_ITEMS")
    if raw_value is None:
        return DEFAULT_REFRESH_PROGRESS_HEARTBEAT_ITEMS
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_REFRESH_PROGRESS_HEARTBEAT_ITEMS
    return max(parsed_value, 1)


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


def _find_latest_completed_sync_run(session: Session) -> SyncRun | None:
    return session.scalar(
        select(SyncRun)
        .where(SyncRun.completed_at.is_not(None))
        .order_by(SyncRun.completed_at.desc(), SyncRun.id.desc())
        .limit(1)
    )


def _find_latest_paused_metadata_refresh_job(session: Session) -> Job | None:
    return session.scalar(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .where(Job.status == JOB_STATUS_PAUSED)
        .order_by(Job.id.desc())
        .limit(1)
    )


def _clear_refresh_lease_fields(payload: dict[str, object]) -> None:
    payload.pop(CLAIMED_AT_FIELD, None)
    payload.pop(HEARTBEAT_AT_FIELD, None)
    payload.pop(WORKER_ID_FIELD, None)


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


def _normalize_extension(*, extension: object, file_name: str) -> str | None:
    if isinstance(extension, str) and extension.strip():
        return extension.strip().lower().lstrip(".")
    if "." in file_name:
        return file_name.rsplit(".", 1)[1].lower()
    return None


def _upsert_file_record(
    session: Session,
    *,
    normalized_item: dict[str, object],
    sync_run_id: int,
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
            extension=_normalize_extension(
                extension=normalized_item.get("extension"),
                file_name=str(normalized_item["name"]),
            ),
            size_bytes=(
                int(normalized_item["size_bytes"])
                if normalized_item.get("size_bytes") is not None
                else None
            ),
            modified_at=_parse_iso_timestamp(normalized_item.get("modified_at")),
            last_seen_sync_run_id=sync_run_id,
        )
        session.add(file_record)
        session.flush()
        return file_record

    file_record.name = str(normalized_item["name"])
    file_record.path = str(normalized_item["path"])
    file_record.mime_type = str(normalized_item["mime_type"])
    file_record.extension = _normalize_extension(
        extension=normalized_item.get("extension"),
        file_name=str(normalized_item["name"]),
    )
    file_record.size_bytes = (
        int(normalized_item["size_bytes"])
        if normalized_item.get("size_bytes") is not None
        else None
    )
    file_record.modified_at = _parse_iso_timestamp(normalized_item.get("modified_at"))
    file_record.is_deleted = False
    file_record.last_seen_sync_run_id = sync_run_id
    session.flush()
    return file_record


def _persist_refresh_results(
    session: Session,
    *,
    raw_items: list[dict[str, object]],
    normalized_items: list[dict[str, object]],
    sync_run_id: int,
    progress_callback: Callable[[int], None] | None = None,
) -> list[dict[str, str]]:
    extraction_failures: list[dict[str, str]] = []
    processed_items = 0

    def record_progress() -> None:
        nonlocal processed_items
        processed_items += 1
        if callable(progress_callback):
            progress_callback(processed_items)

    for raw_item, normalized_item in zip(raw_items, normalized_items, strict=True):
        file_record = _upsert_file_record(
            session,
            normalized_item=normalized_item,
            sync_run_id=sync_run_id,
        )
        extracted_content = session.scalar(
            select(ExtractedContent).where(ExtractedContent.file_id == file_record.id)
        )
        payload = _coerce_content_bytes(raw_item)
        if payload is None:
            if extracted_content is not None:
                session.delete(extracted_content)
                session.flush()
            record_progress()
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
            record_progress()
            continue
        if not extracted_text:
            if extracted_content is not None:
                session.delete(extracted_content)
                session.flush()
            record_progress()
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
        record_progress()

    return extraction_failures


def _finalize_sync_run_snapshot(session: Session, *, sync_run_id: int) -> None:
    session.execute(
        update(FileRecord)
        .where(FileRecord.is_deleted.is_(False))
        .where(
            or_(
                FileRecord.last_seen_sync_run_id.is_(None),
                FileRecord.last_seen_sync_run_id != sync_run_id,
            )
        )
        .values(is_deleted=True)
    )
    session.flush()


def _ensure_running_sync_run(session: Session, job: Job) -> SyncRun:
    if job.sync_run_id is not None:
        sync_run = session.get(SyncRun, job.sync_run_id)
        if sync_run is not None:
            if sync_run.status != JOB_STATUS_RUNNING:
                sync_run.status = JOB_STATUS_RUNNING
                sync_run.completed_at = None
                sync_run.error_message = None
                session.flush()
            return sync_run

    sync_run = SyncRun(status=JOB_STATUS_RUNNING)
    session.add(sync_run)
    session.flush()
    job.sync_run_id = sync_run.id
    session.flush()
    return sync_run


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
                next_status=JOB_STATUS_QUEUED,
                next_payload_json=_serialize_payload(payload),
                error_message=(
                    "Recovered stale running job after restart or downtime and preserved "
                    "saved progress without penalty despite missing or invalid lease metadata."
                ),
            ):
                recovered_count += 1
            continue

        heartbeat_at = _parse_heartbeat_at(payload) or claimed_at
        if heartbeat_at > stale_cutoff:
            continue

        _clear_refresh_lease_fields(payload)

        if apply_stale_recovery_update(
            session,
            job_id=job.id,
            expected_payload_json=snapshot_payload_json,
            next_status=JOB_STATUS_QUEUED,
            next_payload_json=_serialize_payload(payload),
            error_message=(
                "Recovered stale running job after restart or downtime and preserved "
                "saved progress without penalty."
            ),
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
    if is_background_refresh_paused():
        return None
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
    return enqueue_metadata_refresh_with_source(session, source="refresh-endpoint")


def enqueue_metadata_refresh_with_source(session: Session, *, source: str) -> Job:
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
                "source": source,
                ATTEMPT_COUNT_FIELD: 0,
                MAX_ATTEMPTS_FIELD: DEFAULT_MAX_ATTEMPTS,
                ITEMS_SEEN_FIELD: 0,
                BATCH_COUNT_FIELD: 0,
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


def maybe_enqueue_background_refresh(
    session: Session,
    *,
    now: datetime | None = None,
) -> Job | None:
    ensure_refresh_job_schema_ready(session)
    if is_background_refresh_paused():
        return None
    existing_job = _find_existing_active_metadata_refresh_job(session)
    if existing_job is not None:
        return existing_job

    refresh_interval_seconds = get_background_refresh_interval_seconds()
    if refresh_interval_seconds <= 0:
        return None

    latest_sync_run = _find_latest_completed_sync_run(session)
    current_time = now or _utc_now()
    latest_completed_at = (
        _coerce_utc_datetime(latest_sync_run.completed_at)
        if latest_sync_run is not None
        else None
    )
    if latest_completed_at is not None:
        elapsed_seconds = (current_time - latest_completed_at).total_seconds()
        if elapsed_seconds < refresh_interval_seconds:
            return None

    return enqueue_metadata_refresh_with_source(
        session,
        source=BACKGROUND_REFRESH_SOURCE,
    )


def get_refresh_status_snapshot(session: Session) -> dict[str, object]:
    ensure_refresh_job_schema_ready(session)
    control_state = _read_refresh_control_state()
    latest_job = session.scalar(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(1)
    )
    if latest_job is None:
        return {
            "status": "idle",
            "paused": bool(control_state.get("paused")),
            "pause_updated_at": control_state.get("updated_at"),
            "pause_reason": control_state.get("reason"),
        }

    payload = _deserialize_payload(latest_job.payload_json)
    snapshot: dict[str, object] = {
        "status": latest_job.status,
        "paused": bool(control_state.get("paused")),
        "pause_updated_at": control_state.get("updated_at"),
        "pause_reason": control_state.get("reason"),
        "job_id": latest_job.id,
        "job_type": latest_job.job_type,
        "source": payload.get("source"),
        "items_seen": payload.get(ITEMS_SEEN_FIELD, 0),
        "batch_count": payload.get(BATCH_COUNT_FIELD, 0),
        "sync_run_id": latest_job.sync_run_id,
        "error_message": latest_job.error_message,
    }
    if FRONTIER_FIELD in payload and isinstance(payload[FRONTIER_FIELD], list):
        snapshot["frontier_length"] = len(payload[FRONTIER_FIELD])
    claimed_at = _parse_claimed_at(payload)
    heartbeat_at = _parse_heartbeat_at(payload)
    batch_started_at = _parse_iso_timestamp(payload.get(BATCH_STARTED_AT_FIELD))
    last_progress_at = _parse_iso_timestamp(payload.get(LAST_PROGRESS_AT_FIELD))
    last_batch_completed_at = _parse_iso_timestamp(payload.get(LAST_BATCH_COMPLETED_AT_FIELD))
    now = _utc_now()
    if claimed_at is not None:
        snapshot["claimed_at"] = claimed_at.isoformat()
    if heartbeat_at is not None:
        snapshot["heartbeat_at"] = heartbeat_at.isoformat()
        snapshot["heartbeat_age_seconds"] = max(
            int((now - heartbeat_at).total_seconds()),
            0,
        )
    if batch_started_at is not None:
        snapshot["batch_started_at"] = batch_started_at.isoformat()
        snapshot["batch_age_seconds"] = max(
            int((now - batch_started_at).total_seconds()),
            0,
        )
    if last_progress_at is not None:
        snapshot["last_progress_at"] = last_progress_at.isoformat()
        snapshot["progress_age_seconds"] = max(
            int((now - last_progress_at).total_seconds()),
            0,
        )
    if last_batch_completed_at is not None:
        snapshot["last_batch_completed_at"] = last_batch_completed_at.isoformat()
    if isinstance(payload.get(BATCH_FILE_LIMIT_FIELD), int):
        snapshot["batch_file_limit"] = payload[BATCH_FILE_LIMIT_FIELD]
    if isinstance(payload.get(BATCH_STAGE_FIELD), str):
        snapshot["batch_stage"] = payload[BATCH_STAGE_FIELD]
    if isinstance(payload.get(CURRENT_BATCH_SIZE_FIELD), int):
        snapshot["current_batch_size"] = payload[CURRENT_BATCH_SIZE_FIELD]
    if isinstance(payload.get(CURRENT_BATCH_ITEMS_PROCESSED_FIELD), int):
        processed_items = max(payload[CURRENT_BATCH_ITEMS_PROCESSED_FIELD], 0)
        snapshot["current_batch_items_processed"] = processed_items
        if isinstance(payload.get(CURRENT_BATCH_SIZE_FIELD), int):
            snapshot["current_batch_items_remaining"] = max(
                payload[CURRENT_BATCH_SIZE_FIELD] - processed_items,
                0,
            )
    if isinstance(payload.get(LAST_BATCH_SIZE_FIELD), int):
        snapshot["last_batch_size"] = payload[LAST_BATCH_SIZE_FIELD]
    last_batch_duration_seconds = payload.get(LAST_BATCH_DURATION_SECONDS_FIELD)
    if isinstance(last_batch_duration_seconds, (int, float)):
        snapshot["last_batch_duration_seconds"] = float(last_batch_duration_seconds)
    return snapshot


def pause_background_refresh(
    session: Session,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    ensure_refresh_job_schema_ready(session)
    current_time = now or _utc_now()
    active_jobs = session.scalars(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .where(Job.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]))
        .order_by(Job.id.asc())
    ).all()
    for job in active_jobs:
        payload = _deserialize_payload(job.payload_json)
        _clear_refresh_lease_fields(payload)
        job.status = JOB_STATUS_PAUSED
        job.payload_json = _serialize_payload(payload)
        session.flush()
    session.commit()
    control_state = _write_refresh_control_state(
        paused=True,
        now=current_time,
        reason=reason,
    )
    return {
        **control_state,
        "status": JOB_STATUS_PAUSED if active_jobs else "idle",
    }


def resume_background_refresh(
    session: Session,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    ensure_refresh_job_schema_ready(session)
    current_time = now or _utc_now()
    paused_job = _find_latest_paused_metadata_refresh_job(session)
    if paused_job is not None:
        payload = _deserialize_payload(paused_job.payload_json)
        _clear_refresh_lease_fields(payload)
        paused_job.status = JOB_STATUS_QUEUED
        paused_job.payload_json = _serialize_payload(payload)
        session.commit()
    else:
        session.commit()
        if _find_existing_active_metadata_refresh_job(session) is None:
            enqueue_metadata_refresh_with_source(session, source="resume-endpoint")
    control_state = _write_refresh_control_state(
        paused=False,
        now=current_time,
        reason=reason,
    )
    latest_job = session.scalar(
        select(Job)
        .where(Job.job_type == METADATA_REFRESH_JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(1)
    )
    return {
        **control_state,
        "status": latest_job.status if latest_job is not None else "idle",
    }


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

    lease_payload_json = job.payload_json

    def update_running_payload(mutator: Callable[[dict[str, object]], None]) -> None:
        nonlocal lease_payload_json
        payload = _deserialize_payload(lease_payload_json)
        mutator(payload)
        updated_job = apply_running_job_lease_update(
            session,
            job_id=job.id,
            expected_payload_json=lease_payload_json,
            next_status=JOB_STATUS_RUNNING,
            next_payload_json=_serialize_payload(payload),
            error_message=job.error_message,
        )
        if updated_job is None:
            raise LostLeaseError(
                "Refresh job lease was lost while saving mid-batch progress; aborting stale worker."
            )
        lease_payload_json = updated_job.payload_json

    def heartbeat() -> None:
        current_time = _utc_now()

        def apply_heartbeat(payload: dict[str, object]) -> None:
            payload[HEARTBEAT_AT_FIELD] = current_time.isoformat()
            payload[LAST_PROGRESS_AT_FIELD] = current_time.isoformat()
            if not isinstance(payload.get(BATCH_STAGE_FIELD), str):
                payload[BATCH_STAGE_FIELD] = "crawling"

        update_running_payload(apply_heartbeat)

    try:
        active_client = client or create_icloud_web_client()
        payload = _deserialize_payload(lease_payload_json)
        batch_started_at = _utc_now()
        batch_file_limit = get_refresh_batch_file_limit()

        def mark_batch_started(running_payload: dict[str, object]) -> None:
            running_payload["source"] = str(running_payload.get("source") or "refresh-endpoint")
            running_payload["auth_mode"] = active_client.auth_mode
            running_payload[BATCH_FILE_LIMIT_FIELD] = batch_file_limit
            running_payload[BATCH_STAGE_FIELD] = "crawling"
            running_payload[BATCH_STARTED_AT_FIELD] = batch_started_at.isoformat()
            running_payload[CURRENT_BATCH_ITEMS_PROCESSED_FIELD] = 0
            running_payload.pop(CURRENT_BATCH_SIZE_FIELD, None)
            running_payload[LAST_PROGRESS_AT_FIELD] = batch_started_at.isoformat()

        update_running_payload(mark_batch_started)
        can_resume_in_batches = (
            getattr(active_client, "_service", None) is not None
            or type(active_client).list_drive_items_batch is not ICloudWebClient.list_drive_items_batch
        )
        if can_resume_in_batches:
            sync_run = _ensure_running_sync_run(session, job)
            frontier = payload.get(FRONTIER_FIELD)
            if not isinstance(frontier, list):
                frontier = active_client.build_traversal_frontier()
            raw_items, next_frontier, completed_snapshot = active_client.list_drive_items_batch(
                frontier,
                limit=get_refresh_batch_file_limit(),
                heartbeat=heartbeat,
            )
        else:
            raw_items = active_client.list_drive_items(heartbeat=heartbeat)
            next_frontier = []
            completed_snapshot = True
            sync_run = _ensure_running_sync_run(session, job)
        items = [normalize_remote_item(item) for item in raw_items]
        payload = _deserialize_payload(lease_payload_json)
        base_items_seen = int(payload.get(ITEMS_SEEN_FIELD, 0))
        batch_size = len(items)
        last_progress_persisted_at = batch_started_at
        last_progress_persisted_count = 0
        progress_heartbeat_seconds = get_refresh_progress_heartbeat_seconds()
        progress_heartbeat_items = get_refresh_progress_heartbeat_items()

        def mark_batch_extracting(running_payload: dict[str, object]) -> None:
            running_payload["source"] = str(running_payload.get("source") or "refresh-endpoint")
            running_payload["auth_mode"] = active_client.auth_mode
            running_payload[BATCH_FILE_LIMIT_FIELD] = batch_file_limit
            running_payload[BATCH_STAGE_FIELD] = "extracting"
            running_payload[CURRENT_BATCH_SIZE_FIELD] = batch_size
            running_payload[CURRENT_BATCH_ITEMS_PROCESSED_FIELD] = 0
            running_payload[LAST_PROGRESS_AT_FIELD] = _utc_now().isoformat()

        update_running_payload(mark_batch_extracting)

        def persist_mid_batch_progress(processed_count: int) -> None:
            nonlocal last_progress_persisted_at
            nonlocal last_progress_persisted_count
            current_time = _utc_now()
            processed_delta = processed_count - last_progress_persisted_count
            elapsed_seconds = (current_time - last_progress_persisted_at).total_seconds()
            should_persist = (
                processed_count >= batch_size
                or processed_delta >= progress_heartbeat_items
                or elapsed_seconds >= progress_heartbeat_seconds
            )
            if not should_persist:
                return

            def apply_mid_batch_progress(running_payload: dict[str, object]) -> None:
                running_payload["source"] = str(
                    running_payload.get("source") or "refresh-endpoint"
                )
                running_payload["auth_mode"] = active_client.auth_mode
                running_payload[BATCH_FILE_LIMIT_FIELD] = batch_file_limit
                running_payload[BATCH_STAGE_FIELD] = "extracting"
                running_payload[CURRENT_BATCH_SIZE_FIELD] = batch_size
                running_payload[CURRENT_BATCH_ITEMS_PROCESSED_FIELD] = processed_count
                running_payload[ITEMS_SEEN_FIELD] = base_items_seen + processed_count
                running_payload[HEARTBEAT_AT_FIELD] = current_time.isoformat()
                running_payload[LAST_PROGRESS_AT_FIELD] = current_time.isoformat()

            update_running_payload(apply_mid_batch_progress)
            last_progress_persisted_at = current_time
            last_progress_persisted_count = processed_count

        extraction_failures = _persist_refresh_results(
            session,
            raw_items=raw_items,
            normalized_items=items,
            sync_run_id=sync_run.id,
            progress_callback=persist_mid_batch_progress,
        )
        payload = _deserialize_payload(lease_payload_json)
        _clear_refresh_lease_fields(payload)
        payload["source"] = str(payload.get("source") or "refresh-endpoint")
        payload[ITEMS_SEEN_FIELD] = max(
            int(payload.get(ITEMS_SEEN_FIELD, 0)),
            base_items_seen + len(items),
        )
        payload[BATCH_COUNT_FIELD] = int(payload.get(BATCH_COUNT_FIELD, 0)) + 1
        payload["auth_mode"] = active_client.auth_mode
        batch_completed_at = _utc_now()
        payload[LAST_PROGRESS_AT_FIELD] = batch_completed_at.isoformat()
        payload[LAST_BATCH_COMPLETED_AT_FIELD] = batch_completed_at.isoformat()
        payload[LAST_BATCH_SIZE_FIELD] = len(items)
        payload[LAST_BATCH_DURATION_SECONDS_FIELD] = round(
            (batch_completed_at - batch_started_at).total_seconds(),
            3,
        )
        payload.pop(BATCH_STAGE_FIELD, None)
        payload.pop(BATCH_STARTED_AT_FIELD, None)
        payload.pop(CURRENT_BATCH_SIZE_FIELD, None)
        payload.pop(CURRENT_BATCH_ITEMS_PROCESSED_FIELD, None)
        if extraction_failures:
            payload["extraction_failures"] = extraction_failures
        if completed_snapshot:
            _finalize_sync_run_snapshot(session, sync_run_id=sync_run.id)
            sync_run.status = JOB_STATUS_COMPLETED
            sync_run.completed_at = _utc_now()
            sync_run.error_message = None
            payload.pop(FRONTIER_FIELD, None)
            payload.pop(BATCH_COUNT_FIELD, None)
            payload.pop(ATTEMPT_COUNT_FIELD, None)
            payload.pop(MAX_ATTEMPTS_FIELD, None)
            completed_job = apply_running_job_lease_update(
                session,
                job_id=job.id,
                expected_payload_json=lease_payload_json,
                next_status=JOB_STATUS_COMPLETED,
                next_payload_json=_serialize_payload(payload),
                error_message=None,
            )
            return completed_job

        payload[FRONTIER_FIELD] = next_frontier
        continued_job = apply_running_job_lease_update(
            session,
            job_id=job.id,
            expected_payload_json=lease_payload_json,
            next_status=JOB_STATUS_QUEUED,
            next_payload_json=_serialize_payload(payload),
            error_message=None,
        )
        return continued_job
    except LostLeaseError:
        session.rollback()
        return None
    except Exception as exc:
        session.rollback()
        payload = _deserialize_payload(lease_payload_json)
        attempt_count = _parse_attempt_count(payload) + 1
        max_attempts = _parse_max_attempts(payload)

        _clear_refresh_lease_fields(payload)
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
        if next_status == JOB_STATUS_FAILED and job.sync_run_id is not None:
            sync_run = session.get(SyncRun, job.sync_run_id)
            if sync_run is not None:
                sync_run.status = JOB_STATUS_FAILED
                sync_run.completed_at = _utc_now()
                sync_run.error_message = error_message
        return apply_running_job_lease_update(
            session,
            job_id=job.id,
            expected_payload_json=lease_payload_json,
            next_status=next_status,
            next_payload_json=next_payload_json,
            error_message=error_message,
        )
