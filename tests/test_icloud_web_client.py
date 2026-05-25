from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import ANY

import pytest

import icloud_index_service.services.icloud_web_client as client_module
from icloud_index_service.services.icloud_web_client import (
    BROWSER_ASSISTED_AUTH_MODE,
    ICloudWebClientNotReadyError,
    create_icloud_web_client,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.raw = BytesIO(payload)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class FakeDriveNode:
    name: str
    node_type: str
    children: list["FakeDriveNode"] = field(default_factory=list)
    payload: bytes = b""
    size: int | None = None
    modified_at: datetime | None = None
    drivewsid: str | None = None

    @property
    def type(self) -> str:
        return self.node_type

    @property
    def date_modified(self) -> datetime | None:
        return self.modified_at

    @property
    def data(self) -> dict[str, object]:
        return {
            "drivewsid": self.drivewsid or self.name,
            "extension": self.name.rsplit(".", 1)[1] if "." in self.name else "",
        }

    def get_children(self) -> list["FakeDriveNode"]:
        return list(self.children)

    def open(self, **kwargs) -> FakeResponse:
        return FakeResponse(self.payload)


class FakePyiCloudService:
    def __init__(
        self,
        *,
        drive: FakeDriveNode | None = None,
        requires_2fa: bool = False,
        requires_2sa: bool = False,
        is_trusted_session: bool = True,
    ) -> None:
        self.drive = drive
        self.requires_2fa = requires_2fa
        self.requires_2sa = requires_2sa
        self.is_trusted_session = is_trusted_session


def test_create_icloud_web_client_requires_apple_credentials(monkeypatch):
    monkeypatch.delenv("ICLOUD_APPLE_ID", raising=False)
    monkeypatch.delenv("ICLOUD_APPLE_PASSWORD", raising=False)

    with pytest.raises(ICloudWebClientNotReadyError) as exc_info:
        create_icloud_web_client()

    assert "ICLOUD_APPLE_ID" in str(exc_info.value)
    assert "ICLOUD_APPLE_PASSWORD" in str(exc_info.value)


def test_create_icloud_web_client_uses_filesystem_mirror_mode(monkeypatch, tmp_path):
    mirror_root = tmp_path / "icloud"
    (mirror_root / "Documents").mkdir(parents=True)
    (mirror_root / "Documents" / "todo.txt").write_text("mirror mode", encoding="utf-8")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.delenv("ICLOUD_APPLE_ID", raising=False)
    monkeypatch.delenv("ICLOUD_APPLE_PASSWORD", raising=False)

    client = create_icloud_web_client()

    assert client.auth_mode == "filesystem-mirror"
    assert client.list_drive_items() == [
        {
            "id": "filesystem::/Documents/todo.txt",
            "name": "todo.txt",
            "path": "/Documents/todo.txt",
            "extension": "txt",
            "contentType": "text/plain",
            "size": len("mirror mode".encode("utf-8")),
            "modified": ANY,
            "content_bytes": b"mirror mode",
        }
    ]


def test_create_icloud_web_client_surfaces_two_factor_bootstrap_requirement(
    monkeypatch,
):
    monkeypatch.setenv("ICLOUD_APPLE_ID", "user@example.com")
    monkeypatch.setenv("ICLOUD_APPLE_PASSWORD", "secret")
    monkeypatch.setattr(
        client_module,
        "PyiCloudService",
        lambda *args, **kwargs: FakePyiCloudService(requires_2fa=True),
    )

    with pytest.raises(ICloudWebClientNotReadyError) as exc_info:
        create_icloud_web_client()

    assert "two-factor" in str(exc_info.value).lower()


def test_icloud_web_client_lists_drive_files_and_respects_download_size_cap(
    monkeypatch,
):
    root = FakeDriveNode(
        name="root",
        node_type="folder",
        children=[
            FakeDriveNode(
                name="Finance",
                node_type="folder",
                children=[
                    FakeDriveNode(
                        name="Budget.txt",
                        node_type="file",
                        payload=b"Quarterly budget draft",
                        size=22,
                        modified_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
                        drivewsid="budget-node",
                    ),
                    FakeDriveNode(
                        name="Archive.pdf",
                        node_type="file",
                        payload=b"%PDF-1.7 fake payload",
                        size=5000,
                        modified_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
                        drivewsid="archive-node",
                    ),
                ],
            )
        ],
    )
    monkeypatch.setenv("ICLOUD_APPLE_ID", "user@example.com")
    monkeypatch.setenv("ICLOUD_APPLE_PASSWORD", "secret")
    monkeypatch.setenv("ICLOUD_MAX_DOWNLOAD_BYTES", "1024")
    monkeypatch.setattr(
        client_module,
        "PyiCloudService",
        lambda *args, **kwargs: FakePyiCloudService(drive=root),
    )

    client = create_icloud_web_client()
    heartbeat_calls = 0

    def heartbeat() -> None:
        nonlocal heartbeat_calls
        heartbeat_calls += 1

    items = client.list_drive_items(heartbeat=heartbeat)

    assert client.auth_mode == BROWSER_ASSISTED_AUTH_MODE
    assert heartbeat_calls >= 3
    assert items == [
        {
            "id": "budget-node",
            "name": "Budget.txt",
            "path": "/Finance/Budget.txt",
            "extension": "txt",
            "contentType": "text/plain",
            "size": 22,
            "modified": "2026-05-12T00:00:00+00:00",
            "content_bytes": b"Quarterly budget draft",
        },
        {
            "id": "archive-node",
            "name": "Archive.pdf",
            "path": "/Finance/Archive.pdf",
            "extension": "pdf",
            "contentType": "application/pdf",
            "size": 5000,
            "modified": "2026-05-11T00:00:00+00:00",
        },
    ]


def test_icloud_web_client_skips_app_libraries_and_default_excluded_directories(
    monkeypatch,
):
    root = FakeDriveNode(
        name="root",
        node_type="folder",
        children=[
            FakeDriveNode(
                name="node_modules",
                node_type="folder",
                children=[
                    FakeDriveNode(
                        name="left-pad.js",
                        node_type="file",
                        payload=b"module.exports = 0",
                        size=18,
                    )
                ],
            ),
            FakeDriveNode(
                name="Clockology",
                node_type="app_library",
                children=[
                    FakeDriveNode(
                        name="ignored.txt",
                        node_type="file",
                        payload=b"ignore me",
                        size=9,
                    )
                ],
            ),
            FakeDriveNode(
                name="Documents",
                node_type="folder",
                children=[
                    FakeDriveNode(
                        name="Notes.txt",
                        node_type="file",
                        payload=b"hello",
                        size=5,
                        drivewsid="notes-node",
                    )
                ],
            ),
        ],
    )
    monkeypatch.setenv("ICLOUD_APPLE_ID", "user@example.com")
    monkeypatch.setenv("ICLOUD_APPLE_PASSWORD", "secret")
    monkeypatch.setattr(
        client_module,
        "PyiCloudService",
        lambda *args, **kwargs: FakePyiCloudService(drive=root),
    )

    client = create_icloud_web_client()

    items = client.list_drive_items()

    assert items == [
        {
            "id": "notes-node",
            "name": "Notes.txt",
            "path": "/Documents/Notes.txt",
            "extension": "txt",
            "contentType": "text/plain",
            "size": 5,
            "content_bytes": b"hello",
        }
    ]


def test_filesystem_mirror_client_lists_batches_and_respects_excludes_and_size_cap(
    monkeypatch,
    tmp_path,
):
    mirror_root = tmp_path / "icloud"
    (mirror_root / "Documents").mkdir(parents=True)
    (mirror_root / "node_modules").mkdir(parents=True)
    (mirror_root / "Documents" / "tiny.txt").write_text("ok", encoding="utf-8")
    (mirror_root / "Documents" / "large.pdf").write_bytes(b"x" * 2048)
    (mirror_root / "node_modules" / "ignored.txt").write_text("ignore", encoding="utf-8")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("ICLOUD_MAX_DOWNLOAD_BYTES", "1024")

    client = create_icloud_web_client()

    frontier = client.build_traversal_frontier()
    first_batch, next_frontier, completed_snapshot = client.list_drive_items_batch(
        frontier,
        limit=1,
    )
    second_batch, final_frontier, finished = client.list_drive_items_batch(
        next_frontier,
        limit=10,
    )

    assert completed_snapshot is False
    assert first_batch == [
        {
            "id": "filesystem::/Documents/large.pdf",
            "name": "large.pdf",
            "path": "/Documents/large.pdf",
            "extension": "pdf",
            "contentType": "application/pdf",
            "size": 2048,
            "modified": ANY,
        }
    ]
    assert second_batch == [
        {
            "id": "filesystem::/Documents/tiny.txt",
            "name": "tiny.txt",
            "path": "/Documents/tiny.txt",
            "extension": "txt",
            "contentType": "text/plain",
            "size": 2,
            "modified": ANY,
            "content_bytes": b"ok",
        }
    ]
    assert final_frontier == []
    assert finished is True


def test_filesystem_mirror_client_gives_each_top_level_provider_early_attention(
    monkeypatch,
    tmp_path,
):
    mirror_root = tmp_path / "mirrors"
    (mirror_root / "google1").mkdir(parents=True)
    (mirror_root / "google2").mkdir(parents=True)
    (mirror_root / "icloud" / "Deep" / "Nested").mkdir(parents=True)
    (mirror_root / "google1" / "Budget.txt").write_text("g1", encoding="utf-8")
    (mirror_root / "google2" / "Receipt.txt").write_text("g2", encoding="utf-8")
    (mirror_root / "icloud" / "Deep" / "Nested" / "Later.txt").write_text("icloud", encoding="utf-8")

    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    client = create_icloud_web_client()

    first_batch, next_frontier, completed_snapshot = client.list_drive_items_batch(
        client.build_traversal_frontier(),
        limit=2,
    )
    second_batch, final_frontier, finished = client.list_drive_items_batch(
        next_frontier,
        limit=10,
    )

    assert completed_snapshot is False
    assert [item["path"] for item in first_batch] == [
        "/google1/Budget.txt",
        "/google2/Receipt.txt",
    ]
    assert [item["path"] for item in second_batch] == ["/icloud/Deep/Nested/Later.txt"]
    assert final_frontier == []
    assert finished is True
