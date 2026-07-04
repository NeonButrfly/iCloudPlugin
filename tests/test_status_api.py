from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import icloud_index_service.main as main_module
import icloud_index_service.services.status_service as status_service_module
from icloud_index_service.db import get_session
from icloud_index_service.models.base import Base
from icloud_index_service.models.classification_job import ClassificationJob
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.job import Job
from icloud_index_service.models.sync_run import SyncRun


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "status.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_status_data(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    try:
        sync_run = SyncRun(status="running")
        session.add(sync_run)
        session.commit()
        session.refresh(sync_run)

        session.add(
            Job(
                job_type="metadata-refresh",
                status="running",
                payload_json=json.dumps(
                    {
                        "source": "background-scan",
                        "items_seen": 42,
                        "batch_count": 4,
                        "frontier": ["/icloud/Documents", "/google1/Appeals"],
                    }
                ),
                sync_run_id=sync_run.id,
            )
        )

        file_one = FileRecord(
            external_id="file-1",
            name="Appeal.docx",
            path="/google1/Appeal.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=123,
        )
        file_two = FileRecord(
            external_id="file-2",
            name="Receipt.pdf",
            path="/icloud/Receipt.pdf",
            mime_type="application/pdf",
            size_bytes=456,
        )
        file_three = FileRecord(
            external_id="file-3",
            name="Deleted.txt",
            path="/google2/Deleted.txt",
            mime_type="text/plain",
            size_bytes=10,
            is_deleted=True,
        )
        session.add_all([file_one, file_two, file_three])
        session.commit()
        session.refresh(file_one)
        session.refresh(file_two)

        session.add_all(
            [
                ClassificationJob(
                    file_id=file_one.id,
                    status="queued",
                    priority_bucket="manual-feedback",
                    priority_rank=1,
                    source_fingerprint="fp-1",
                ),
                ClassificationJob(
                    file_id=file_two.id,
                    status="completed",
                    priority_bucket="background",
                    priority_rank=5,
                    source_fingerprint="fp-2",
                ),
                ClassificationState(
                    file_id=file_one.id,
                    submission_status="queued",
                    primary_label="medical",
                ),
                ClassificationState(
                    file_id=file_two.id,
                    submission_status="completed",
                    primary_label="receipt",
                ),
            ]
        )
        session.commit()
    finally:
        session.close()


def test_status_summary_returns_live_counts_and_vault_counts(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    _seed_status_data(session_factory)

    mirror_root = tmp_path / "mirrors"
    matched_source = mirror_root / "google1" / "Appeal.docx"
    matched_source.parent.mkdir(parents=True, exist_ok=True)
    matched_source.write_text("Appeal body", encoding="utf-8")
    unmatched_source = mirror_root / "icloud" / "Legacy.txt"
    unmatched_source.parent.mkdir(parents=True, exist_ok=True)
    unmatched_source.write_text("Legacy body", encoding="utf-8")

    vault_root = tmp_path / "document-vault"
    (vault_root / "01 Classified" / "medical").mkdir(parents=True)
    (vault_root / "01 Classified" / "medical" / "Appeal - medical.md").write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                f'canonical_source_path: {json.dumps(str(matched_source))}',
                'canonical_source_hash: "abc123"',
                'last_seen_filename: "Appeal.docx"',
                "---",
                "",
                "# Appeal",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (vault_root / "02 Needs Review").mkdir(parents=True)
    (vault_root / "02 Needs Review" / "Receipt - review.md").write_text(
        "\n".join(
            [
                "---",
                'type: "classified-document"',
                f'canonical_source_path: {json.dumps(str(unmatched_source))}',
                'canonical_source_hash: "def456"',
                'last_seen_filename: "Legacy.txt"',
                "---",
                "",
                "# Legacy",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (vault_root / "_system" / "extracted-markdown").mkdir(parents=True)
    (vault_root / "_system" / "extracted-markdown" / "Appeal.md").write_text(
        "body",
        encoding="utf-8",
    )
    (vault_root / "Home.md").write_text("# Home", encoding="utf-8")
    sync_status_path = tmp_path / "cloud-vault-sync-status.json"
    sync_status_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-31T18:00:00+00:00",
                "overall_status": "degraded",
                "required_failures_present": True,
                "degraded_remotes": ["icloud", "gdrive1"],
                "required_failure_remotes": ["icloud"],
                "remote_statuses": [
                    {
                        "remote_name": "icloud",
                        "required": True,
                        "status": "failed",
                        "detail": "rclone bisync failed",
                    },
                    {
                        "remote_name": "gdrive1",
                        "required": False,
                        "status": "unreachable",
                        "detail": "Remote gdrive1 is configured but not reachable. Skipping.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLOUD_VAULT_SYNC_STATUS_PATH", str(sync_status_path))
    monkeypatch.setenv("PLUGIN_API_TOKEN", "secret-token")
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    monkeypatch.setattr(
        status_service_module,
        "fetch_classifier_health",
        lambda: {
            "ok": True,
            "real_ingestion_allowed": True,
            "queue_depth": 0,
            "classify_model": "qwen2.5:3b",
            "vision_model": "qwen2.5vl:3b",
        },
    )
    main_module.app.dependency_overrides[get_session] = override_get_session
    main_module.app.state.auth_session_state = "configured"

    try:
        with TestClient(main_module.app) as client:
            response = client.get(
                "/status/summary",
                headers={"Authorization": "Bearer secret-token"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["service_health"] == {"status": "ok", "database": "ok"}
    assert payload["auth_status"] == {"status": "configured", "database": "ok"}
    assert payload["refresh_status"] == {
        "status": "running",
        "paused": False,
        "pause_updated_at": None,
        "pause_reason": None,
        "job_id": 1,
        "job_type": "metadata-refresh",
        "source": "background-scan",
        "items_seen": 42,
        "batch_count": 4,
        "sync_run_id": 1,
        "error_message": None,
        "frontier_length": 2,
    }
    assert payload["classifier_health"] == {
        "ok": True,
        "real_ingestion_allowed": True,
        "queue_depth": 0,
        "classify_model": "qwen2.5:3b",
        "vision_model": "qwen2.5vl:3b",
    }
    assert payload["classifier_runtime"] == {
        "classifier_mode": "mcp_fallback_only",
        "background_classification_enabled": False,
        "mcp_fallback_classification_enabled": True,
        "classifier_fallback_available": True,
        "local_classifier_configured": False,
        "queued_classifier_jobs": 1,
        "queued_jobs_auto_running": False,
        "queued_cloud_vault_tasks": 0,
        "queued_cloud_vault_tasks_auto_running": False,
    }
    assert payload["capabilities"] == {
        "document_vault_write_capability": True,
        "upload_capability": False,
        "chatgpt_uploaded_file_import_capability": False,
        "server_side_import_capability": True,
        "external_data_note_capability": True,
        "task_queue_health": "ok",
        "task_queue_counts": {},
        "dedupe_job_capability": True,
        "non_destructive_dedupe_archive_capability": True,
        "restore_change_set_capability": True,
        "allowed_import_roots": [
            "/srv/cloud-vault/imports",
            "/srv/cloud-vault/dropbox",
            "/mnt/imports",
        ],
    }
    assert payload["classification_job_counts"] == {"completed": 1, "queued": 1}
    assert payload["classification_state_counts"] == {"completed": 1, "queued": 1}
    assert payload["cloud_vault_task_counts"] == {}
    assert payload["cloud_vault_task_type_counts"] == {}
    assert payload["provider_counts"] == {"google1": 1, "icloud": 1}
    assert payload["vault_counts"] == {
        "vault_root": str(vault_root.resolve()),
        "vault_root_exists": True,
        "classified_files": 1,
        "needs_review_files": 1,
        "attachments_files": 0,
        "extracted_markdown_files": 1,
        "classification_index_present": False,
        "home_note_present": True,
    }
    assert payload["generated_note_context_gaps"] == {
        "vault_root": str(vault_root.resolve()),
        "mirror_root": str(mirror_root.resolve()),
        "total_generated_notes": 2,
        "notes_missing_any_context": 2,
        "notes_missing_source_parser": 2,
        "notes_missing_heuristic_primary_hint": 2,
        "notes_missing_hybrid_live_source": 2,
        "missing_context_with_matching_completed_state": 0,
        "missing_context_with_matching_queued_state": 1,
        "missing_context_with_matching_other_state": 0,
        "missing_context_without_matching_state": 1,
        "missing_context_source_file_present": 2,
        "missing_context_source_file_missing": 0,
    }
    assert payload["cloud_vault_sync"] == {
        "status_file": str(sync_status_path.resolve()),
        "status_file_present": True,
        "generated_at": "2026-05-31T18:00:00+00:00",
        "overall_status": "degraded",
        "required_failures_present": True,
        "degraded_remotes": ["icloud", "gdrive1"],
        "required_failure_remotes": ["icloud"],
        "remote_statuses": [
            {
                "remote_name": "icloud",
                "required": True,
                "status": "failed",
                "detail": "rclone bisync failed",
            },
            {
                "remote_name": "gdrive1",
                "required": False,
                "status": "unreachable",
                "detail": "Remote gdrive1 is configured but not reachable. Skipping.",
            },
        ],
    }
    assert isinstance(payload["generated_at"], str)


def test_status_summary_requires_bearer_auth_when_plugin_token_is_set(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    _seed_status_data(session_factory)

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("PLUGIN_API_TOKEN", "secret-token")
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    monkeypatch.setattr(
        status_service_module,
        "fetch_classifier_health",
        lambda: {"ok": True, "classify_model": "qwen2.5:3b", "vision_model": "qwen2.5vl:3b"},
    )
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            unauthorized = client.get("/status/summary")
            authorized = client.get(
                "/status/summary",
                headers={"Authorization": "Bearer secret-token"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_status_readiness_returns_live_summary_plus_readiness_report(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    _seed_status_data(session_factory)

    mirror_root = tmp_path / "mirrors"
    (mirror_root / "google1").mkdir(parents=True, exist_ok=True)
    (mirror_root / "google1" / "Appeal.docx").write_text("Appeal body", encoding="utf-8")

    vault_root = tmp_path / "document-vault"
    (vault_root / "01 Classified").mkdir(parents=True, exist_ok=True)
    (vault_root / "Classification Index.md").write_text("# Index", encoding="utf-8")
    (vault_root / "Home.md").write_text("# Home", encoding="utf-8")

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("PLUGIN_API_TOKEN", "secret-token")
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    monkeypatch.setattr(
        status_service_module,
        "fetch_classifier_health",
        lambda: {
            "ok": True,
            "real_ingestion_allowed": True,
            "queue_depth": 0,
            "classify_model": "qwen2.5:3b",
            "vision_model": "qwen2.5vl:3b",
        },
    )
    main_module.app.dependency_overrides[get_session] = override_get_session
    main_module.app.state.auth_session_state = "configured"

    try:
        with TestClient(main_module.app) as client:
            response = client.get(
                "/status/readiness",
                headers={"Authorization": "Bearer secret-token"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status_summary"]["service_health"] == {"status": "ok", "database": "ok"}
    assert payload["status_summary"]["auth_status"] == {"status": "configured", "database": "ok"}
    assert payload["status_summary"]["change_set_counts"] == {}
    assert payload["status_summary"]["document_vault_note_counts"] == {"total": 0, "deleted": 0}
    assert payload["product_readiness"]["success_criteria"][
        "cloudflare_remote_mcp_exists_and_is_the_intended_external_path"
    ]["status"] == "met"
    assert payload["product_readiness"]["success_criteria"][
        "classifier_runtime_still_uses_qwen_models"
    ]["status"] == "met"
    assert payload["product_readiness"]["success_criteria"][
        "auth_and_deployment_story_is_real"
    ]["status"] == "met"
    assert isinstance(payload["generated_at"], str)


def test_fetch_classifier_health_handles_httpx_client_init_failure(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_API_TOKEN", "secret-token")

    class BrokenClient:
        def __init__(self, *args, **kwargs) -> None:
            raise FileNotFoundError("missing CA bundle")

    monkeypatch.setattr(status_service_module.httpx, "Client", BrokenClient)

    payload = status_service_module.fetch_classifier_health()

    assert payload == {
        "ok": False,
        "error": "classifier-health-client-init-failed",
        "detail": "missing CA bundle",
    }
