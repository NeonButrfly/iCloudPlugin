from pathlib import Path

import pytest

from icloud_index_service.services.file_mutation_service import (
    FileMutationPolicyError,
    FileNamespace,
    delete_file_by_path,
    import_duplicate_quarantine_to_changes_backup,
    is_hidden_internal_path,
    restore_change_set,
    resolve_live_path,
    resolve_namespace_root,
)


def test_resolve_namespace_root_maps_document_vault_to_runtime_mount(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    vault_root = tmp_path / "cloud-vault" / "document-vault"
    mirror_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    assert resolve_namespace_root(FileNamespace.DOCUMENT_VAULT) == vault_root.resolve()


def test_hidden_internal_path_blocks_normal_reads(tmp_path: Path):
    namespace_root = tmp_path / "google1"
    hidden_file = namespace_root / "_CHANGES_BACKUP" / "change-set-1" / "meta.json"
    hidden_file.parent.mkdir(parents=True)
    hidden_file.write_text("{}", encoding="utf-8")

    assert is_hidden_internal_path(hidden_file, namespace_root=namespace_root) is True


def test_resolve_live_path_rejects_underscore_paths_for_normal_access(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    google_root = mirror_root / "google1"
    google_root.mkdir(parents=True)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    with pytest.raises(FileMutationPolicyError, match="underscore-prefixed"):
        resolve_live_path(
            namespace=FileNamespace.GOOGLE1,
            relative_path="_CHANGES_BACKUP/secret.txt",
            allow_internal=False,
        )


def test_resolve_live_path_allows_internal_access_for_restore(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    google_root = mirror_root / "google1"
    target = google_root / "_CHANGES_BACKUP" / "secret.txt"
    target.parent.mkdir(parents=True)
    target.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    assert resolve_live_path(
        namespace=FileNamespace.GOOGLE1,
        relative_path="_CHANGES_BACKUP/secret.txt",
        allow_internal=True,
    ) == target.resolve()


def test_delete_moves_live_file_into_changes_backup(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    result = delete_file_by_path(
        namespace=FileNamespace.GOOGLE1,
        relative_path="Cases/Appeal.txt",
        actor="pytest",
    )

    assert result["change_set_id"]
    assert not file_path.exists()
    assert Path(result["backup_path"]).exists()


def test_restore_change_set_returns_deleted_file_to_live_path(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    deleted = delete_file_by_path(
        namespace=FileNamespace.GOOGLE1,
        relative_path="Cases/Appeal.txt",
        actor="pytest",
    )
    restored = restore_change_set(change_set_id=deleted["change_set_id"], actor="pytest-restore")

    assert restored["status"] == "restored"
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "appeal"


def test_import_duplicate_quarantine_creates_legacy_change_sets(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    quarantine_file = mirror_root / "google1" / "_DUPLICATE_QUARANTINE" / "dup.txt"
    quarantine_file.parent.mkdir(parents=True, exist_ok=True)
    quarantine_file.write_text("duplicate", encoding="utf-8")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    result = import_duplicate_quarantine_to_changes_backup(actor="pytest")

    assert result["imported_files"] == 1
    assert result["change_sets_created"] == 1
    assert not quarantine_file.exists()
