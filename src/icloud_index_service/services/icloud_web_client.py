from __future__ import annotations

import mimetypes
import os
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyicloud import PyiCloudService
from pyicloud.services.drive import DriveNode

BROWSER_ASSISTED_AUTH_MODE = "browser-assisted-apple-web"
FILESYSTEM_MIRROR_AUTH_MODE = "filesystem-mirror"
DEFAULT_SOURCE_MODE = "apple-web"
FILESYSTEM_MIRROR_SOURCE_MODE = "filesystem-mirror"
HeartbeatCallback = Callable[[], None]
DEFAULT_COOKIE_DIRECTORY = ".runtime/pyicloud"
DEFAULT_MAX_DOWNLOAD_BYTES = 1_048_576
DEFAULT_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)


class ICloudWebClientNotReadyError(RuntimeError):
    pass


def _read_required_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped_value = value.strip()
    return stripped_value or None


def _read_int_env(name: str, *, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return max(int(raw_value), 0)


def _read_bool_env(name: str, *, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_float_env(name: str) -> float | None:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None
    return float(raw_value)


def _read_csv_env(name: str) -> frozenset[str]:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return frozenset()
    return frozenset(
        part.strip()
        for part in raw_value.split(",")
        if part.strip()
    )


def _ensure_cookie_directory() -> str:
    cookie_directory = _read_required_env("ICLOUD_COOKIE_DIRECTORY") or DEFAULT_COOKIE_DIRECTORY
    cookie_path = Path(cookie_directory)
    cookie_path.mkdir(parents=True, exist_ok=True)
    return str(cookie_path)


def _read_source_mode() -> str:
    raw_value = os.environ.get("ICLOUD_SOURCE_MODE")
    if raw_value is None or not raw_value.strip():
        return DEFAULT_SOURCE_MODE
    return raw_value.strip().lower()


def _guess_content_type(file_name: str) -> str:
    content_type, _ = mimetypes.guess_type(file_name)
    return content_type or "application/octet-stream"


def _get_extension(file_name: str) -> str:
    _, extension = os.path.splitext(file_name)
    return extension.lstrip(".")


class ICloudWebClient:
    """Server-side wrapper around pyicloud's iCloud Drive support."""

    def __init__(
        self,
        *,
        service: Any | None = None,
        auth_mode: str = BROWSER_ASSISTED_AUTH_MODE,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        excluded_directory_names: frozenset[str] = DEFAULT_EXCLUDED_DIRECTORY_NAMES,
    ) -> None:
        self.auth_mode = auth_mode
        self._service = service
        self._max_download_bytes = max_download_bytes
        self._excluded_directory_names = excluded_directory_names

    def list_drive_items(
        self,
        *,
        heartbeat: HeartbeatCallback | None = None,
    ) -> list[dict[str, object]]:
        if self._service is None:
            raise ICloudWebClientNotReadyError("The iCloud web client has no active service.")
        drive_root = self._service.drive
        items: list[dict[str, object]] = []
        self._walk_drive_node(
            drive_root,
            parent_path="",
            heartbeat=heartbeat,
            items=items,
        )
        return items

    def build_traversal_frontier(self) -> list[dict[str, object]]:
        if self._service is None:
            raise ICloudWebClientNotReadyError("The iCloud web client has no active service.")
        root_node = self._service.drive.root
        return [self._serialize_frontier_entry(root_node, parent_path="")]

    def list_drive_items_batch(
        self,
        frontier: list[dict[str, object]] | None,
        *,
        limit: int,
        heartbeat: HeartbeatCallback | None = None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], bool]:
        if self._service is None:
            raise ICloudWebClientNotReadyError("The iCloud web client has no active service.")
        active_frontier = list(frontier or self.build_traversal_frontier())
        items: list[dict[str, object]] = []

        while active_frontier and len(items) < limit:
            if heartbeat is not None:
                heartbeat()

            entry = active_frontier.pop()
            entry_type = str(entry["type"])
            entry_name = str(entry["name"])
            if entry_type == "app_library":
                continue
            if entry_type == "file":
                items.append(self._serialize_file_entry(entry))
                continue
            if entry_name in self._excluded_directory_names:
                continue

            folder_node = self._resolve_frontier_folder_entry(entry)
            child_parent_path = str(entry["path"])
            children = folder_node.get_children()
            for child in reversed(children):
                active_frontier.append(
                    self._serialize_frontier_entry(
                        child,
                        parent_path=child_parent_path,
                    )
                )

        return items, active_frontier, not active_frontier

    def _walk_drive_node(
        self,
        node: Any,
        *,
        parent_path: str,
        heartbeat: HeartbeatCallback | None,
        items: list[dict[str, object]],
    ) -> None:
        if heartbeat is not None:
            heartbeat()

        if node.type == "app_library":
            return
        if node.type == "file":
            items.append(self._serialize_file_node(node, parent_path=parent_path))
            return
        if node.name in self._excluded_directory_names:
            return

        current_path = parent_path
        if node.name != "root":
            current_path = f"{parent_path}/{node.name}" if parent_path else f"/{node.name}"

        for child in node.get_children():
            self._walk_drive_node(
                child,
                parent_path=current_path,
                heartbeat=heartbeat,
                items=items,
            )

    def _serialize_frontier_entry(
        self,
        node: Any,
        *,
        parent_path: str,
    ) -> dict[str, object]:
        node_path = parent_path
        if node.name != "root":
            node_path = f"{parent_path}/{node.name}" if parent_path else f"/{node.name}"
        return {
            "type": node.type,
            "name": node.name,
            "path": node_path,
            "drivewsid": node.data.get("drivewsid"),
            "docwsid": node.data.get("docwsid"),
            "share_id": node.data.get("shareID"),
            "zone": node.data.get("zone"),
            "size": node.size,
            "date_modified": getattr(node, "date_modified", None).isoformat()
            if isinstance(getattr(node, "date_modified", None), datetime)
            else None,
        }

    def _resolve_frontier_folder_entry(self, entry: dict[str, object]) -> DriveNode:
        drive_service = self._service.drive
        drivewsid = entry.get("drivewsid")
        if not isinstance(drivewsid, str) or not drivewsid:
            raise ICloudWebClientNotReadyError("Missing drivewsid for iCloud folder traversal.")
        if str(entry["name"]) == "root":
            return drive_service.root
        node_data = drive_service.get_node_data(drivewsid, entry.get("share_id"))
        return DriveNode(drive_service, node_data)

    def _serialize_file_node(
        self,
        node: Any,
        *,
        parent_path: str,
    ) -> dict[str, object]:
        file_path = f"{parent_path}/{node.name}" if parent_path else f"/{node.name}"
        extension = _get_extension(node.name)
        payload: dict[str, object] = {
            "id": node.data.get("drivewsid") or node.data.get("docwsid") or file_path,
            "name": node.name,
            "path": file_path,
            "extension": extension,
            "contentType": _guess_content_type(node.name),
            "size": node.size,
        }

        modified_at = getattr(node, "date_modified", None)
        if isinstance(modified_at, datetime):
            payload["modified"] = modified_at.isoformat()

        if node.size is None or node.size <= self._max_download_bytes:
            content_bytes = self._download_file_bytes(node)
            if content_bytes is not None:
                payload["content_bytes"] = content_bytes

        return payload

    def _serialize_file_entry(self, entry: dict[str, object]) -> dict[str, object]:
        file_name = str(entry["name"])
        file_path = str(entry["path"])
        extension = _get_extension(file_name)
        payload: dict[str, object] = {
            "id": entry.get("drivewsid") or entry.get("docwsid") or file_path,
            "name": file_name,
            "path": file_path,
            "extension": extension,
            "contentType": _guess_content_type(file_name),
            "size": entry.get("size"),
        }
        modified_at = entry.get("date_modified")
        if isinstance(modified_at, str) and modified_at:
            payload["modified"] = modified_at

        size = entry.get("size")
        if size is None or (isinstance(size, int) and size <= self._max_download_bytes):
            content_bytes = self._download_file_entry_bytes(entry)
            if content_bytes is not None:
                payload["content_bytes"] = content_bytes

        return payload

    def _download_file_bytes(self, node: Any) -> bytes | None:
        try:
            with node.open(stream=True) as response:
                return response.raw.read(self._max_download_bytes + 1)[
                    : self._max_download_bytes
                ]
        except Exception:
            return None

    def _download_file_entry_bytes(self, entry: dict[str, object]) -> bytes | None:
        if self._service is None:
            return None
        docwsid = entry.get("docwsid")
        zone = entry.get("zone")
        if not isinstance(docwsid, str) or not docwsid or not isinstance(zone, str) or not zone:
            return None
        try:
            response = self._service.drive.get_file(docwsid, zone=zone, stream=True)
            return response.raw.read(self._max_download_bytes + 1)[
                : self._max_download_bytes
            ]
        except Exception:
            return None


class FilesystemMirrorICloudWebClient(ICloudWebClient):
    def __init__(
        self,
        *,
        mirror_root: Path,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        excluded_directory_names: frozenset[str] = DEFAULT_EXCLUDED_DIRECTORY_NAMES,
    ) -> None:
        super().__init__(
            service=None,
            auth_mode=FILESYSTEM_MIRROR_AUTH_MODE,
            max_download_bytes=max_download_bytes,
            excluded_directory_names=excluded_directory_names,
        )
        self._mirror_root = mirror_root.resolve()

    def list_drive_items(
        self,
        *,
        heartbeat: HeartbeatCallback | None = None,
    ) -> list[dict[str, object]]:
        frontier = self.build_traversal_frontier()
        items: list[dict[str, object]] = []
        while frontier:
            batch_items, frontier, _ = self.list_drive_items_batch(
                frontier,
                limit=max(len(frontier), 1_000),
                heartbeat=heartbeat,
            )
            items.extend(batch_items)
        return items

    def build_traversal_frontier(self) -> list[dict[str, object]]:
        return [
            {
                "type": "folder",
                "name": "root",
                "path": "",
                "local_path": str(self._mirror_root),
            }
        ]

    def list_drive_items_batch(
        self,
        frontier: list[dict[str, object]] | None,
        *,
        limit: int,
        heartbeat: HeartbeatCallback | None = None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], bool]:
        active_frontier = deque(frontier or self.build_traversal_frontier())
        items: list[dict[str, object]] = []

        while active_frontier and len(items) < limit:
            if heartbeat is not None:
                heartbeat()

            entry = active_frontier.popleft()
            entry_type = str(entry["type"])
            entry_name = str(entry["name"])
            local_path = Path(str(entry["local_path"]))

            if entry_type == "folder":
                if entry_name != "root" and entry_name in self._excluded_directory_names:
                    continue
                if not local_path.exists() or not local_path.is_dir():
                    continue
                child_entries = self._list_child_entries(local_path, parent_path=str(entry["path"]))
                for child_entry in child_entries:
                    active_frontier.append(child_entry)
                continue

            if entry_type == "file":
                if local_path.exists() and local_path.is_file():
                    items.append(self._serialize_local_file_entry(local_path, logical_path=str(entry["path"])))

        return items, list(active_frontier), not active_frontier

    def _list_child_entries(self, directory: Path, *, parent_path: str) -> list[dict[str, object]]:
        child_entries: list[dict[str, object]] = []
        for child_path in sorted(directory.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower())):
            child_logical_path = f"{parent_path}/{child_path.name}" if parent_path else f"/{child_path.name}"
            child_entries.append(
                {
                    "type": "folder" if child_path.is_dir() else "file",
                    "name": child_path.name,
                    "path": child_logical_path,
                    "local_path": str(child_path),
                }
            )
        return child_entries

    def _serialize_local_file_entry(self, file_path: Path, *, logical_path: str) -> dict[str, object]:
        stat_result = file_path.stat()
        payload: dict[str, object] = {
            "id": f"filesystem::{logical_path}",
            "name": file_path.name,
            "path": logical_path,
            "extension": file_path.suffix.lstrip("."),
            "contentType": _guess_content_type(file_path.name),
            "size": stat_result.st_size,
            "modified": datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat(),
        }
        if stat_result.st_size <= self._max_download_bytes:
            payload["content_bytes"] = file_path.read_bytes()
        return payload


def create_icloud_web_client() -> ICloudWebClient:
    source_mode = _read_source_mode()
    max_download_bytes = _read_int_env(
        "ICLOUD_MAX_DOWNLOAD_BYTES",
        default=DEFAULT_MAX_DOWNLOAD_BYTES,
    )
    excluded_directory_names = (
        DEFAULT_EXCLUDED_DIRECTORY_NAMES
        | _read_csv_env("ICLOUD_EXCLUDED_DIRECTORY_NAMES")
    )
    if source_mode == FILESYSTEM_MIRROR_SOURCE_MODE:
        mirror_root = _read_required_env("ICLOUD_MIRROR_ROOT")
        if mirror_root is None:
            raise ICloudWebClientNotReadyError(
                "Filesystem mirror access is not ready: ICLOUD_MIRROR_ROOT must be configured."
            )
        mirror_root_path = Path(mirror_root)
        if not mirror_root_path.exists() or not mirror_root_path.is_dir():
            raise ICloudWebClientNotReadyError(
                "Filesystem mirror access is not ready: ICLOUD_MIRROR_ROOT does not exist or is not a directory."
            )
        return FilesystemMirrorICloudWebClient(
            mirror_root=mirror_root_path,
            max_download_bytes=max_download_bytes,
            excluded_directory_names=excluded_directory_names,
        )

    apple_id = _read_required_env("ICLOUD_APPLE_ID")
    password = _read_required_env("ICLOUD_APPLE_PASSWORD")
    if apple_id is None or password is None:
        raise ICloudWebClientNotReadyError(
            "Direct iCloud Drive access is not ready: ICLOUD_APPLE_ID and "
            "ICLOUD_APPLE_PASSWORD to be configured."
        )

    service = PyiCloudService(
        apple_id,
        password=password,
        cookie_directory=_ensure_cookie_directory(),
        verify=_read_bool_env("ICLOUD_VERIFY_TLS", default=True),
        client_id=_read_required_env("ICLOUD_CLIENT_ID"),
        with_family=_read_bool_env("ICLOUD_WITH_FAMILY", default=True),
        china_mainland=_read_bool_env("ICLOUD_CHINA_MAINLAND", default=False),
        accept_terms=_read_bool_env("ICLOUD_ACCEPT_TERMS", default=False),
        refresh_interval=_read_float_env("ICLOUD_REFRESH_INTERVAL_SECONDS"),
    )
    if getattr(service, "requires_2fa", False) or getattr(service, "requires_2sa", False):
        raise ICloudWebClientNotReadyError(
            "Direct iCloud Drive access is not ready: two-factor authentication is still required for this Apple account. "
            "Complete one trusted interactive pyicloud login first so the persisted "
            "session cookies can be reused by the service."
        )
    if not getattr(service, "is_trusted_session", True):
        raise ICloudWebClientNotReadyError(
            "Direct iCloud Drive access is not ready: the current Apple session is not trusted yet. Trust the session during "
            "interactive bootstrap before running refresh jobs."
        )

    return ICloudWebClient(
        service=service,
        max_download_bytes=max_download_bytes,
        excluded_directory_names=excluded_directory_names,
    )
