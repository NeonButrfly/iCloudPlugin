from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import icloud_index_service.main as main_module
from icloud_index_service.db import get_session
from icloud_index_service.models.base import Base
from icloud_index_service.models.dedupe_group import DedupeGroup
from icloud_index_service.models.dedupe_group_item import DedupeGroupItem
from icloud_index_service.models.file import FileRecord


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "files-api.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _override_get_session(session_factory: sessionmaker[Session]):
    def _dependency():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    return _dependency


def _seed_file_record(
    session_factory: sessionmaker[Session],
    *,
    external_id: str,
    name: str,
    path: str,
    mime_type: str = "text/plain",
) -> int:
    session = session_factory()
    try:
        file_record = FileRecord(
            external_id=external_id,
            name=name,
            path=path,
            mime_type=mime_type,
        )
        session.add(file_record)
        session.commit()
        session.refresh(file_record)
        return file_record.id
    finally:
        session.close()


def test_delete_file_route_moves_file_into_changes_backup(tmp_path, monkeypatch):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/delete",
                json={"namespace": "google1", "relative_path": "Cases/Appeal.txt"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "deleted"
    assert not file_path.exists()
    assert Path(payload["backup_path"]).exists()


def test_restore_change_set_route_returns_file_to_live_path(tmp_path, monkeypatch):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            deleted = client.post(
                "/files/ops/delete",
                json={"namespace": "google1", "relative_path": "Cases/Appeal.txt"},
            )
            restored = client.post(
                "/files/ops/restore",
                json={"change_set_id": deleted.json()["change_set_id"]},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert deleted.status_code == 200
    assert restored.status_code == 200
    assert restored.json()["status"] == "restored"
    assert file_path.exists()


def test_create_document_vault_note_route_writes_structured_note(tmp_path, monkeypatch):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    vault_root = tmp_path / "cloud-vault" / "document-vault"
    source_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("appeal", encoding="utf-8")
    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_file_record(
        session_factory,
        external_id="file-appeal",
        name="Appeal.txt",
        path="/google1/Cases/Appeal.txt",
    )

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/document-vault/note",
                json={
                    "relative_folder": "01 Classified/appeal",
                    "visible_title": "Appeal",
                    "summary": "Appeal summary.",
                    "file_id": file_id,
                    "attach_originals": True,
                },
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    note_path = Path(payload["note_path"])
    assert note_path.exists()
    assert payload["change_set_id"]
    note_text = note_path.read_text(encoding="utf-8")
    assert "type: classified-document" in note_text
    assert "## Original File" in note_text


def test_create_document_vault_note_route_requires_source_reference(tmp_path, monkeypatch):
    vault_root = tmp_path / "cloud-vault" / "document-vault"
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/document-vault/note",
                json={
                    "relative_folder": "01 Classified/appeal",
                    "visible_title": "Appeal",
                    "summary": "Appeal summary.",
                },
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "Either file_id or canonical_source_path is required."


def test_get_change_set_route_returns_indexed_change_set(tmp_path, monkeypatch):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            deleted = client.post(
                "/files/ops/delete",
                json={"namespace": "google1", "relative_path": "Cases/Appeal.txt"},
            )
            change_set = client.get(
                f"/files/ops/change-sets/{deleted.json()['change_set_id']}",
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert change_set.status_code == 200
    payload = change_set.json()
    assert payload["change_set_id"] == deleted.json()["change_set_id"]
    assert payload["status"] == "deleted"


def test_sync_manual_feedback_events_route_returns_ingest_summary(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    monkeypatch.setattr(
        "icloud_index_service.api.files.sync_manual_feedback_events",
        lambda session, limit: {
            "scanned": limit,
            "created": 2,
            "unchanged": 1,
            "event_ids": ["evt-1", "evt-2"],
        },
    )
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/manual-feedback/sync",
                json={"limit": 3},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "scanned": 3,
        "created": 2,
        "unchanged": 1,
        "event_ids": ["evt-1", "evt-2"],
    }


def test_analyze_duplicate_groups_route_returns_candidates(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    monkeypatch.setattr(
        "icloud_index_service.api.files.analyze_duplicate_groups",
        lambda session, namespaces, limit: {
            "created_groups": ["dup-1"],
            "groups": [
                {
                    "dedupe_group_id": "dup-1",
                    "status": "candidate",
                    "canonical_item_path": "/google1/Cases/Appeal.txt",
                    "duplicate_count": 1,
                    "members": [
                        "/google1/Cases/Appeal.txt",
                        "/google2/Cases/Appeal.txt",
                    ],
                }
            ],
            "received_namespaces": namespaces,
            "received_limit": limit,
        },
    )
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/dedupe/analyze",
                json={"namespaces": ["google1", "google2", "icloud"], "limit": 5},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_groups"] == ["dup-1"]
    assert payload["received_namespaces"] == ["google1", "google2", "icloud"]
    assert payload["received_limit"] == 5


def test_get_dedupe_group_route_returns_indexed_group(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        group = DedupeGroup(
            dedupe_group_id="dup-1",
            group_fingerprint="hash:size",
            strategy="exact_hash",
            status="candidate",
            canonical_item_path="/google1/Cases/Appeal.txt",
            total_size_bytes=12,
            duplicate_count=1,
            recommended_keep_file_record_id=1,
            confidence=0.99,
            reason="Exact hash match.",
            evidence_json='{"members":["/google1/Cases/Appeal.txt","/google2/Cases/Appeal.txt"]}',
            decision_notes="Generated by dry run.",
        )
        session.add(group)
        session.flush()
        first_file = FileRecord(
            external_id="first",
            name="Appeal.txt",
            path="/google1/Cases/Appeal.txt",
            mime_type="text/plain",
            extension="txt",
            size_bytes=6,
        )
        second_file = FileRecord(
            external_id="second",
            name="Appeal.txt",
            path="/google2/Cases/Appeal.txt",
            mime_type="text/plain",
            extension="txt",
            size_bytes=6,
        )
        session.add_all([first_file, second_file])
        session.flush()
        group.canonical_file_record_id = first_file.id
        group.recommended_keep_file_record_id = first_file.id
        session.add_all(
            [
                DedupeGroupItem(
                    dedupe_group_id=group.id,
                    file_record_id=first_file.id,
                    path_at_analysis_time="/google1/Cases/Appeal.txt",
                    content_hash="abc",
                    size_bytes=6,
                    similarity_score=1.0,
                    decision_role="canonical",
                    source_exists=True,
                ),
                DedupeGroupItem(
                    dedupe_group_id=group.id,
                    file_record_id=second_file.id,
                    path_at_analysis_time="/google2/Cases/Appeal.txt",
                    content_hash="abc",
                    size_bytes=6,
                    similarity_score=1.0,
                    decision_role="duplicate",
                    source_exists=True,
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.get("/files/ops/dedupe/groups/dup-1")
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["dedupe_group_id"] == "dup-1"
    assert payload["strategy"] == "exact_hash"
    assert len(payload["members"]) == 2


def test_start_dedupe_job_route_returns_job_payload(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    monkeypatch.setattr(
        "icloud_index_service.api.files.start_dedupe_job",
        lambda session, **kwargs: {"job_id": "job123", "status": "queued", "queued_count": 5, "message": "ok"},
    )
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/dedupe/jobs/start",
                json={"namespaces": ["google1", "icloud"], "strategy": "exact_hash"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["job_id"] == "job123"


def test_apply_dedupe_group_route_returns_change_set(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    monkeypatch.setattr(
        "icloud_index_service.api.files.apply_dedupe_group",
        lambda session, **kwargs: {
            "status": "dry_run",
            "change_set_id": "cs123",
            "kept_file_id": 1,
            "moved_to_backup": [],
            "dry_run": True,
            "message": "ok",
        },
    )
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/dedupe/groups/apply",
                json={
                    "dedupe_group_id": "dup123",
                    "keep_file_id": 1,
                    "move_to_backup_file_ids": [2],
                    "dry_run": True,
                },
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["change_set_id"] == "cs123"


def test_queue_cloud_vault_task_route_returns_task_payload(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/tasks/queue",
                json={
                    "task_type": "restore_change_set",
                    "input": {"change_set_id": "abc123"},
                    "idempotency_key": "restore-abc123",
                },
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"]


def test_queue_chatgpt_first_file_note_route_returns_task_payload(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = _override_get_session(session_factory)

    try:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/files/ops/tasks/document-vault/note/file-id/chatgpt-first",
                json={
                    "file_id": 7,
                    "chatgpt_relative_folder": "01 Classified/appeal",
                    "chatgpt_visible_title": "Appeal",
                    "chatgpt_summary": "Appeal summary.",
                },
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"]
