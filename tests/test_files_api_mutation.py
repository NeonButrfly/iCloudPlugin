from pathlib import Path

from fastapi.testclient import TestClient

import icloud_index_service.main as main_module


def test_delete_file_route_moves_file_into_changes_backup(tmp_path, monkeypatch):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/files/ops/delete",
            json={"namespace": "google1", "relative_path": "Cases/Appeal.txt"},
        )

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

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)

    with TestClient(main_module.app) as client:
        deleted = client.post(
            "/files/ops/delete",
            json={"namespace": "google1", "relative_path": "Cases/Appeal.txt"},
        )
        restored = client.post(
            "/files/ops/restore",
            json={"change_set_id": deleted.json()["change_set_id"]},
        )

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

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)

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

    assert response.status_code == 200
    payload = response.json()
    note_path = Path(payload["note_path"])
    assert note_path.exists()
    note_text = note_path.read_text(encoding="utf-8")
    assert "type: classified-document" in note_text
    assert "## Original File" in note_text
