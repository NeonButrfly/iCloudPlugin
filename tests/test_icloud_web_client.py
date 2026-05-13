from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO

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
