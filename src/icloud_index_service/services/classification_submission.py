from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import httpx
from sqlalchemy import Select, and_, case, exists, not_, or_, select, update
from sqlalchemy.orm import Session

from icloud_index_service.models.classification_job import ClassificationJob
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord

CLASSIFICATION_STATUS_QUEUED = "queued"
CLASSIFICATION_STATUS_RUNNING = "running"
CLASSIFICATION_STATUS_COMPLETED = "completed"
CLASSIFICATION_STATUS_FAILED = "failed"
DEFAULT_CLASSIFICATION_MAX_ATTEMPTS = 3
DEFAULT_CLASSIFICATION_SUBMISSION_CONCURRENCY = 2
DEFAULT_CLASSIFICATION_SUBMISSION_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_CLASSIFICATION_STALE_RUNNING_SECONDS = 300
DEFAULT_CLASSIFICATION_RETRY_BACKOFF_SECONDS = 0
DEFAULT_CLASSIFIER_API_URL = "http://192.168.50.196:4319"
CLASSIFIER_UPLOAD_ENDPOINT = "/classify/upload"
CLASSIFIER_INGESTION_MODE = "real-folder"
PRIORITY_BUCKET_DOCUMENT = "document"
PRIORITY_BUCKET_TEXT_BACKED = "text-backed"
PRIORITY_BUCKET_IMAGE = "image"
PRIORITY_BUCKET_OTHER = "other"
PRIORITY_BUCKETS = (
    PRIORITY_BUCKET_DOCUMENT,
    PRIORITY_BUCKET_TEXT_BACKED,
    PRIORITY_BUCKET_IMAGE,
    PRIORITY_BUCKET_OTHER,
)
PRIORITY_RANKS = {
    PRIORITY_BUCKET_DOCUMENT: 0,
    PRIORITY_BUCKET_TEXT_BACKED: 1,
    PRIORITY_BUCKET_IMAGE: 2,
    PRIORITY_BUCKET_OTHER: 3,
}
DOCUMENT_EXTENSIONS = frozenset(
    {
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "txt",
        "md",
        "markdown",
        "csv",
        "html",
        "htm",
    }
)
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"})
SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
TEXT_BACKED_BUCKET_EXCLUDED_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS


class ClassifierSubmissionNotReadyError(RuntimeError):
    pass


class PermanentClassifierSubmissionError(RuntimeError):
    pass


def _is_retryable_classifier_rejection(*, status_code: int, response_text: str) -> bool:
    normalized_text = response_text.lower()
    return status_code == 409 and (
        "real-folder ingestion is blocked" in normalized_text
        or "readiness-report-missing-or-blocked" in normalized_text
        or "manual-real-ingestion-enable-still-required" in normalized_text
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc_datetime(raw_value: datetime | None) -> datetime | None:
    if raw_value is None:
        return None
    if raw_value.tzinfo is None:
        return raw_value.replace(tzinfo=timezone.utc)
    return raw_value.astimezone(timezone.utc)


def _read_bool_env(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def get_classification_submission_enabled() -> bool:
    return _read_bool_env("CLASSIFICATION_SUBMISSION_ENABLED", default=True)


def get_classification_submission_concurrency() -> int:
    raw_value = os.getenv("CLASSIFICATION_SUBMISSION_CONCURRENCY")
    if raw_value is None:
        return DEFAULT_CLASSIFICATION_SUBMISSION_CONCURRENCY
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_CLASSIFICATION_SUBMISSION_CONCURRENCY
    return min(max(parsed_value, 1), 4)


def get_classification_submission_poll_interval_seconds() -> float:
    raw_value = os.getenv("CLASSIFICATION_SUBMISSION_POLL_INTERVAL_SECONDS")
    if raw_value is None:
        return DEFAULT_CLASSIFICATION_SUBMISSION_POLL_INTERVAL_SECONDS
    try:
        parsed_value = float(raw_value)
    except ValueError:
        return DEFAULT_CLASSIFICATION_SUBMISSION_POLL_INTERVAL_SECONDS
    return max(parsed_value, 0.1)


def get_classification_max_attempts() -> int:
    raw_value = os.getenv("CLASSIFICATION_MAX_ATTEMPTS")
    if raw_value is None:
        return DEFAULT_CLASSIFICATION_MAX_ATTEMPTS
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_CLASSIFICATION_MAX_ATTEMPTS
    return max(parsed_value, 1)


def get_classification_retry_backoff_seconds() -> int:
    raw_value = os.getenv("CLASSIFICATION_RETRY_BACKOFF_SECONDS")
    if raw_value is None:
        return DEFAULT_CLASSIFICATION_RETRY_BACKOFF_SECONDS
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return DEFAULT_CLASSIFICATION_RETRY_BACKOFF_SECONDS
    return max(parsed_value, 0)


def _normalize_extension(extension: str | None, *, file_name: str | None = None) -> str:
    raw_value = (extension or "").strip().lower().lstrip(".")
    if raw_value:
        return raw_value
    if file_name and "." in file_name:
        return file_name.rsplit(".", 1)[1].lower()
    return ""


def compute_file_content_hash(file_path: Path) -> str:
    digest = sha256()
    with file_path.open("rb") as payload_stream:
        for chunk in iter(lambda: payload_stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classifiable_extension_predicate() -> object:
    return FileRecord.extension.in_(sorted(SUPPORTED_EXTENSIONS))


def _document_extension_predicate() -> object:
    return FileRecord.extension.in_(sorted(DOCUMENT_EXTENSIONS))


def _image_extension_predicate() -> object:
    return FileRecord.extension.in_(sorted(IMAGE_EXTENSIONS))


def _build_priority_case() -> object:
    return case(
        (_document_extension_predicate(), PRIORITY_RANKS[PRIORITY_BUCKET_DOCUMENT]),
        (
            and_(
                _image_extension_predicate(),
            ),
            PRIORITY_RANKS[PRIORITY_BUCKET_IMAGE],
        ),
        (
            and_(
                ExtractedContent.file_id.is_not(None),
                not_(FileRecord.extension.in_(sorted(TEXT_BACKED_BUCKET_EXCLUDED_EXTENSIONS))),
            ),
            PRIORITY_RANKS[PRIORITY_BUCKET_TEXT_BACKED],
        ),
        else_=PRIORITY_RANKS[PRIORITY_BUCKET_OTHER],
    )


def compute_source_fingerprint(
    *,
    file_record: FileRecord,
    extracted_content: ExtractedContent | None,
) -> str:
    if extracted_content is not None and extracted_content.content_hash:
        return f"text:{extracted_content.content_hash}"

    modified_at = _coerce_utc_datetime(file_record.modified_at)
    meta_payload = "|".join(
        [
            file_record.path,
            file_record.mime_type,
            str(file_record.size_bytes or ""),
            modified_at.isoformat() if modified_at is not None else "",
        ]
    )
    return f"meta:{sha256(meta_payload.encode('utf-8')).hexdigest()}"


def _determine_priority_bucket(
    *,
    file_record: FileRecord,
    extracted_content: ExtractedContent | None,
) -> tuple[str, int]:
    extension = _normalize_extension(file_record.extension, file_name=file_record.name)
    if extension in DOCUMENT_EXTENSIONS:
        return PRIORITY_BUCKET_DOCUMENT, PRIORITY_RANKS[PRIORITY_BUCKET_DOCUMENT]
    if extracted_content is not None and extracted_content.content_hash:
        return PRIORITY_BUCKET_TEXT_BACKED, PRIORITY_RANKS[PRIORITY_BUCKET_TEXT_BACKED]
    if extension in IMAGE_EXTENSIONS:
        return PRIORITY_BUCKET_IMAGE, PRIORITY_RANKS[PRIORITY_BUCKET_IMAGE]
    return PRIORITY_BUCKET_OTHER, PRIORITY_RANKS[PRIORITY_BUCKET_OTHER]


def _build_candidate_statement(
    *,
    bucket: str,
    limit: int,
    offset: int = 0,
) -> Select[tuple[FileRecord, ExtractedContent | None, ClassificationState | None]]:
    active_job_exists = exists(
        select(ClassificationJob.id).where(
            ClassificationJob.file_id == FileRecord.id,
            ClassificationJob.status.in_(
                [CLASSIFICATION_STATUS_QUEUED, CLASSIFICATION_STATUS_RUNNING]
            ),
        )
    )

    statement = (
        select(FileRecord, ExtractedContent, ClassificationState)
        .outerjoin(ExtractedContent, ExtractedContent.file_id == FileRecord.id)
        .outerjoin(ClassificationState, ClassificationState.file_id == FileRecord.id)
        .where(FileRecord.is_deleted.is_(False))
        .where(_classifiable_extension_predicate())
        .where(~active_job_exists)
        .order_by(FileRecord.id.asc())
        .offset(offset)
        .limit(limit)
    )

    if bucket == PRIORITY_BUCKET_DOCUMENT:
        return statement.where(_document_extension_predicate())
    if bucket == PRIORITY_BUCKET_TEXT_BACKED:
        return statement.where(
            ExtractedContent.file_id.is_not(None),
            not_(FileRecord.extension.in_(sorted(TEXT_BACKED_BUCKET_EXCLUDED_EXTENSIONS))),
        )
    if bucket == PRIORITY_BUCKET_IMAGE:
        return statement.where(_image_extension_predicate())
    return statement.where(
        not_(FileRecord.extension.in_(sorted(DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS)))
    )


def _upsert_classification_state(
    session: Session,
    *,
    file_record: FileRecord,
    source_fingerprint: str,
    submission_status: str,
) -> ClassificationState:
    state = session.scalar(
        select(ClassificationState).where(ClassificationState.file_id == file_record.id)
    )
    if state is None:
        state = ClassificationState(
            file_id=file_record.id,
            source_fingerprint=source_fingerprint,
            source_size_bytes=file_record.size_bytes,
            source_modified_at=file_record.modified_at,
            submission_status=submission_status,
        )
        session.add(state)
    else:
        state.source_fingerprint = source_fingerprint
        state.source_size_bytes = file_record.size_bytes
        state.source_modified_at = file_record.modified_at
        state.submission_status = submission_status
        state.last_error = None if submission_status == CLASSIFICATION_STATUS_QUEUED else state.last_error
    session.flush()
    return state


def enqueue_classification_backfill(
    session: Session,
    *,
    limit: int,
) -> list[ClassificationJob]:
    if limit <= 0:
        return []

    created_jobs: list[ClassificationJob] = []
    candidate_chunk_size = max(limit * 5, 25)

    for bucket in PRIORITY_BUCKETS:
        if len(created_jobs) >= limit:
            break

        offset = 0
        while len(created_jobs) < limit:
            remaining = limit - len(created_jobs)
            statement = _build_candidate_statement(
                bucket=bucket,
                limit=max(candidate_chunk_size, remaining),
                offset=offset,
            )
            candidates = session.execute(statement).all()
            if not candidates:
                break

            offset += len(candidates)

            for file_record, extracted_content, state in candidates:
                source_fingerprint = compute_source_fingerprint(
                    file_record=file_record,
                    extracted_content=extracted_content,
                )
                if (
                    state is not None
                    and state.submission_status == CLASSIFICATION_STATUS_COMPLETED
                    and state.source_fingerprint == source_fingerprint
                ):
                    continue

                priority_bucket, priority_rank = _determine_priority_bucket(
                    file_record=file_record,
                    extracted_content=extracted_content,
                )
                if priority_bucket != bucket:
                    continue

                job = ClassificationJob(
                    file_id=file_record.id,
                    status=CLASSIFICATION_STATUS_QUEUED,
                    priority_bucket=priority_bucket,
                    priority_rank=priority_rank,
                    source_fingerprint=source_fingerprint,
                    max_attempts=get_classification_max_attempts(),
                )
                session.add(job)
                _upsert_classification_state(
                    session,
                    file_record=file_record,
                    source_fingerprint=source_fingerprint,
                    submission_status=CLASSIFICATION_STATUS_QUEUED,
                )
                created_jobs.append(job)
                if len(created_jobs) >= limit:
                    break

    session.commit()
    return created_jobs


def recover_stale_running_classification_jobs(
    session: Session,
    *,
    stale_after_seconds: int = DEFAULT_CLASSIFICATION_STALE_RUNNING_SECONDS,
    now: datetime | None = None,
) -> int:
    current_time = now or _utc_now()
    stale_cutoff = current_time - timedelta(seconds=stale_after_seconds)
    stale_jobs = session.scalars(
        select(ClassificationJob)
        .where(ClassificationJob.status == CLASSIFICATION_STATUS_RUNNING)
        .where(
            or_(
                ClassificationJob.heartbeat_at.is_(None),
                ClassificationJob.heartbeat_at < stale_cutoff,
            )
        )
        .order_by(ClassificationJob.id.asc())
    ).all()

    for job in stale_jobs:
        job.status = CLASSIFICATION_STATUS_QUEUED
        job.worker_id = None
        job.claimed_at = None
        job.heartbeat_at = None
        job.updated_at = current_time
        job.error_message = (
            "Recovered stale running classification job after restart or downtime "
            "and preserved saved progress without penalty."
        )

    if stale_jobs:
        session.commit()
    return len(stale_jobs)


def claim_next_classification_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> ClassificationJob | None:
    current_time = now or _utc_now()
    queued_job = session.scalar(
        select(ClassificationJob)
        .where(ClassificationJob.status == CLASSIFICATION_STATUS_QUEUED)
        .where(
            or_(
                ClassificationJob.next_attempt_at.is_(None),
                ClassificationJob.next_attempt_at <= current_time,
            )
        )
        .order_by(ClassificationJob.priority_rank.asc(), ClassificationJob.id.asc())
        .limit(1)
    )
    if queued_job is None:
        return None

    updated_rows = session.execute(
        update(ClassificationJob)
        .where(ClassificationJob.id == queued_job.id)
        .where(ClassificationJob.status == CLASSIFICATION_STATUS_QUEUED)
        .values(
            status=CLASSIFICATION_STATUS_RUNNING,
            worker_id=worker_id,
            claimed_at=current_time,
            heartbeat_at=current_time,
            updated_at=current_time,
            error_message=None,
        )
    ).rowcount
    if updated_rows == 0:
        session.rollback()
        return None

    session.commit()
    return session.get(ClassificationJob, queued_job.id)


def _resolve_mirror_root() -> Path:
    source_mode = (os.getenv("ICLOUD_SOURCE_MODE") or "").strip().lower()
    mirror_root = (os.getenv("ICLOUD_MIRROR_ROOT") or "").strip()
    if source_mode != "filesystem-mirror" or not mirror_root:
        raise ClassifierSubmissionNotReadyError(
            "Classification submission requires filesystem-mirror source mode and a configured ICLOUD_MIRROR_ROOT."
        )
    mirror_root_path = Path(mirror_root).resolve()
    if not mirror_root_path.exists() or not mirror_root_path.is_dir():
        raise ClassifierSubmissionNotReadyError(
            "Classification submission requires an existing filesystem mirror root."
        )
    return mirror_root_path


def resolve_classification_file_path(file_record: FileRecord) -> Path:
    mirror_root = _resolve_mirror_root()
    relative_path = file_record.path.lstrip("/")
    candidate = (mirror_root / relative_path).resolve()
    if candidate != mirror_root and mirror_root not in candidate.parents:
        raise PermanentClassifierSubmissionError("Resolved file path escapes the configured mirror root.")
    return candidate


@dataclass(slots=True)
class ClassifierApiClient:
    base_url: str
    api_token: str | None
    ingestion_mode: str = CLASSIFIER_INGESTION_MODE
    timeout_seconds: float = 1800.0

    def submit_file(
        self,
        *,
        file_path: Path,
        file_name: str,
        canonical_source_path: str | None = None,
        canonical_source_hash: str | None = None,
        last_seen_filename: str | None = None,
    ) -> dict[str, object]:
        headers = {}
        if self.api_token:
            headers["X-API-Key"] = self.api_token
        form_data = {"ingestion_mode": self.ingestion_mode}
        if canonical_source_path:
            form_data["canonical_source_path"] = canonical_source_path
        if canonical_source_hash:
            form_data["canonical_source_hash"] = canonical_source_hash
        if last_seen_filename:
            form_data["last_seen_filename"] = last_seen_filename

        try:
            with file_path.open("rb") as payload_stream:
                response = httpx.post(
                    f"{self.base_url.rstrip('/')}{CLASSIFIER_UPLOAD_ENDPOINT}",
                    headers=headers,
                    data=form_data,
                    files={"file": (file_name, payload_stream)},
                    timeout=self.timeout_seconds,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Classifier request failed: {exc}") from exc

        if response.status_code >= 500:
            raise RuntimeError(
                f"Classifier API returned {response.status_code}: {response.text[:500]}"
            )
        if response.status_code >= 400:
            if _is_retryable_classifier_rejection(
                status_code=response.status_code,
                response_text=response.text,
            ):
                raise ClassifierSubmissionNotReadyError(
                    f"Classifier API not ready yet ({response.status_code}): {response.text[:500]}"
                )
            raise PermanentClassifierSubmissionError(
                f"Classifier API rejected submission with {response.status_code}: {response.text[:500]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Classifier API returned invalid JSON.") from exc

        if not payload.get("ok", False):
            raise RuntimeError(
                f"Classifier processing failed: returncode={payload.get('returncode')} "
                f"stderr={payload.get('stderr_tail', '')}"
            )

        return payload


def create_classifier_api_client() -> ClassifierApiClient:
    return ClassifierApiClient(
        base_url=(os.getenv("CLASSIFIER_API_URL") or DEFAULT_CLASSIFIER_API_URL).strip(),
        api_token=(os.getenv("CLASSIFIER_API_TOKEN") or "").strip() or None,
    )


def _extract_record_field(response_payload: dict[str, object], field_name: str) -> object:
    record = response_payload.get("record")
    if isinstance(record, dict):
        return record.get(field_name)
    return None


def _persist_completed_classification(
    session: Session,
    *,
    job: ClassificationJob,
    file_record: FileRecord,
    response_payload: dict[str, object],
    now: datetime,
) -> ClassificationJob:
    state = _upsert_classification_state(
        session,
        file_record=file_record,
        source_fingerprint=job.source_fingerprint,
        submission_status=CLASSIFICATION_STATUS_COMPLETED,
    )
    state.last_submitted_at = job.claimed_at or now
    state.last_completed_at = now
    state.classifier_note_path = (
        _extract_record_field(response_payload, "note_path")
        if isinstance(_extract_record_field(response_payload, "note_path"), str)
        else None
    )
    record = response_payload.get("record")
    state.classifier_manifest_record = json.dumps(record) if isinstance(record, dict) else None
    primary_label = _extract_record_field(response_payload, "primary_label")
    state.primary_label = primary_label if isinstance(primary_label, str) else None
    summary = _extract_record_field(response_payload, "summary")
    state.summary = summary if isinstance(summary, str) else None
    confidence = _extract_record_field(response_payload, "confidence")
    state.confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    reasoning = _extract_record_field(response_payload, "reasoning")
    state.reasoning = reasoning if isinstance(reasoning, str) else None
    state.response_payload_json = json.dumps(response_payload)
    state.last_error = None

    job.status = CLASSIFICATION_STATUS_COMPLETED
    job.worker_id = None
    job.claimed_at = None
    job.heartbeat_at = None
    job.next_attempt_at = None
    job.classifier_response_json = json.dumps(response_payload)
    job.error_message = None
    job.updated_at = now
    session.commit()
    return job


def _persist_failed_classification(
    session: Session,
    *,
    job: ClassificationJob,
    file_record: FileRecord,
    error_message: str,
    now: datetime,
    permanent: bool,
) -> ClassificationJob:
    attempt_count = job.attempt_count + 1
    job.attempt_count = attempt_count
    job.worker_id = None
    job.claimed_at = None
    job.heartbeat_at = None
    job.updated_at = now
    job.error_message = error_message

    should_fail = permanent or attempt_count >= job.max_attempts
    if should_fail:
        job.status = CLASSIFICATION_STATUS_FAILED
        job.next_attempt_at = None
    else:
        job.status = CLASSIFICATION_STATUS_QUEUED
        backoff_seconds = get_classification_retry_backoff_seconds()
        job.next_attempt_at = now + timedelta(seconds=backoff_seconds) if backoff_seconds > 0 else now

    state = _upsert_classification_state(
        session,
        file_record=file_record,
        source_fingerprint=job.source_fingerprint,
        submission_status=job.status,
    )
    state.last_submitted_at = state.last_submitted_at or now
    state.last_error = error_message
    if should_fail:
        state.last_completed_at = now

    session.commit()
    return job


def run_next_classification_job(
    session: Session,
    *,
    client: ClassifierApiClient | object | None = None,
    worker_id: str,
    stale_after_seconds: int = DEFAULT_CLASSIFICATION_STALE_RUNNING_SECONDS,
    now: datetime | None = None,
) -> ClassificationJob | None:
    current_time = now or _utc_now()
    recover_stale_running_classification_jobs(
        session,
        stale_after_seconds=stale_after_seconds,
        now=current_time,
    )
    claimed_job = claim_next_classification_job(
        session,
        worker_id=worker_id,
        now=current_time,
    )
    if claimed_job is None:
        return None

    file_record = session.get(FileRecord, claimed_job.file_id)
    if file_record is None:
        claimed_job.status = CLASSIFICATION_STATUS_FAILED
        claimed_job.attempt_count += 1
        claimed_job.worker_id = None
        claimed_job.claimed_at = None
        claimed_job.heartbeat_at = None
        claimed_job.next_attempt_at = None
        claimed_job.updated_at = current_time
        claimed_job.error_message = "Indexed file record no longer exists."
        session.commit()
        return claimed_job

    active_client = client or create_classifier_api_client()
    try:
        file_path = resolve_classification_file_path(file_record)
        if not file_path.exists() or not file_path.is_file():
            raise RuntimeError(
                f"Mirrored file is missing for submission: {file_path}"
            )
        canonical_source_hash = compute_file_content_hash(file_path)
        response_payload = active_client.submit_file(
            file_path=file_path,
            file_name=file_record.name,
            canonical_source_path=str(file_path),
            canonical_source_hash=canonical_source_hash,
            last_seen_filename=file_record.name,
        )
        return _persist_completed_classification(
            session,
            job=claimed_job,
            file_record=file_record,
            response_payload=response_payload,
            now=_utc_now(),
        )
    except PermanentClassifierSubmissionError as exc:
        return _persist_failed_classification(
            session,
            job=claimed_job,
            file_record=file_record,
            error_message=str(exc),
            now=_utc_now(),
            permanent=True,
        )
    except (ClassifierSubmissionNotReadyError, RuntimeError, httpx.HTTPError) as exc:
        return _persist_failed_classification(
            session,
            job=claimed_job,
            file_record=file_record,
            error_message=str(exc),
            now=_utc_now(),
            permanent=False,
        )
