from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import icloud_index_service.main as main_module
from icloud_index_service.db import get_session
from icloud_index_service.models.base import Base


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
                    "canonical_source_path": str(source_path),
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
