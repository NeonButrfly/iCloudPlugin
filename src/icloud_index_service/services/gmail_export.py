from __future__ import annotations

import argparse
import base64
import json
import re
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error
from urllib import parse
from urllib import request


GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_REFRESH_GRANT_TYPE = "refresh_token"
DEFAULT_EXPORT_QUERY = "-in:chats -in:spam -in:trash"
DEFAULT_STATE_FILENAME = ".gmail-export-state.json"
DEFAULT_MAX_RESULTS = 500
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@dataclass(slots=True)
class ExportAttachment:
    filename: str
    mime_type: str
    payload: bytes


@dataclass(slots=True)
class ExportMessage:
    gmail_message_id: str
    thread_id: str
    subject: str
    from_header: str
    to_header: str
    cc_header: str
    delivered_at: datetime
    label_names: list[str]
    snippet: str
    body_text: str
    body_html: str
    attachments: list[ExportAttachment] = field(default_factory=list)


def _sanitize_filename_fragment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip())
    cleaned = cleaned.strip("-")
    return cleaned or "no-subject"


def _sanitize_attachment_filename(value: str) -> str:
    candidate = Path(value or "").name.strip()
    return candidate or "attachment.bin"


def build_export_file_path(output_root: Path, message: ExportMessage) -> Path:
    timestamp = message.delivered_at.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    subject_fragment = _sanitize_filename_fragment(message.subject)
    return (
        output_root
        / message.delivered_at.astimezone(UTC).strftime("%Y")
        / message.delivered_at.astimezone(UTC).strftime("%m")
        / f"{timestamp}--{subject_fragment}--{message.gmail_message_id}.md"
    )


def _encode_yaml_scalar(value: str) -> str:
    cleaned = value or ""
    if re.fullmatch(r"[A-Za-z0-9@._:+/\-]+", cleaned):
        return cleaned
    return json.dumps(cleaned, ensure_ascii=False)


def render_export_markdown(message: ExportMessage) -> str:
    label_values = ", ".join(message.label_names)
    body = message.body_text.strip() or message.body_html.strip() or message.snippet.strip()
    lines = [
        "---",
        f"gmail_message_id: {_encode_yaml_scalar(message.gmail_message_id)}",
        f"thread_id: {_encode_yaml_scalar(message.thread_id)}",
        f"subject: {_encode_yaml_scalar(message.subject)}",
        f"from: {_encode_yaml_scalar(message.from_header)}",
        f"to: {_encode_yaml_scalar(message.to_header)}",
        f"cc: {_encode_yaml_scalar(message.cc_header)}",
        f"delivered_at: {_encode_yaml_scalar(message.delivered_at.astimezone(UTC).isoformat())}",
        f"labels: {_encode_yaml_scalar(label_values)}",
        f"snippet: {_encode_yaml_scalar(message.snippet)}",
        "---",
        "",
        f"# {message.subject or 'No Subject'}",
        "",
        "## Metadata",
        "",
        f"- From: {message.from_header}",
        f"- To: {message.to_header}",
        f"- Cc: {message.cc_header or '(none)'}",
        f"- Labels: {label_values or '(none)'}",
        "",
        "## Body",
        "",
        body,
    ]
    if message.attachments:
        lines.extend(["", "## Attachments", ""])
        for attachment in message.attachments:
            lines.append(f"- {attachment.filename}")
    return "\n".join(lines).rstrip() + "\n"


def write_export_message(
    output_root: Path,
    message: ExportMessage,
    *,
    download_attachments: bool,
) -> Path:
    export_path = build_export_file_path(output_root, message)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(render_export_markdown(message), encoding="utf-8")
    if download_attachments and message.attachments:
        attachment_root = export_path.parent / f"{export_path.stem}.attachments"
        attachment_root.mkdir(parents=True, exist_ok=True)
        for attachment in message.attachments:
            destination = attachment_root / _sanitize_attachment_filename(attachment.filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(attachment.payload)
    return export_path


def _load_authorized_user_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Authorized user file {path} did not contain an object.")
    return payload


def _persist_authorized_user_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _refresh_access_token(authorized_user: dict[str, Any]) -> str:
    token_uri = str(authorized_user.get("token_uri") or "https://oauth2.googleapis.com/token").strip()
    client_id = str(authorized_user.get("client_id") or "").strip()
    client_secret = str(authorized_user.get("client_secret") or "").strip()
    refresh_token = str(authorized_user.get("refresh_token") or "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise ValueError("Authorized user file is missing client_id, client_secret, or refresh_token.")

    body = parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": TOKEN_REFRESH_GRANT_TYPE,
        }
    ).encode("utf-8")
    req = request.Request(
        token_uri,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("Token refresh response did not include access_token.")
    authorized_user["token"] = access_token
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in > 0:
        authorized_user["expiry"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    scopes = authorized_user.get("scopes")
    if not scopes:
        authorized_user["scopes"] = [GMAIL_READONLY_SCOPE]
    return access_token


def _gmail_request(
    access_token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = parse.urlencode(
        {key: value for key, value in (params or {}).items() if value not in (None, "")},
        doseq=True,
    )
    url = f"{GMAIL_API_ROOT}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    req = request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _decode_message_part_body(body: dict[str, Any]) -> bytes:
    data = str(body.get("data") or "")
    if not data:
        return b""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _extract_header(headers: list[dict[str, Any]], header_name: str) -> str:
    target = header_name.lower()
    for header in headers:
        if str(header.get("name") or "").strip().lower() == target:
            return str(header.get("value") or "").strip()
    return ""


def _walk_message_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [payload]
    discovered: list[dict[str, Any]] = []
    while parts:
        current = parts.pop()
        discovered.append(current)
        children = current.get("parts")
        if isinstance(children, list):
            parts.extend(part for part in children if isinstance(part, dict))
    return discovered


def _decode_part_text(parts: list[dict[str, Any]], mime_type: str) -> str:
    for part in parts:
        if str(part.get("mimeType") or "").strip().lower() != mime_type:
            continue
        payload = _decode_message_part_body(part.get("body") or {})
        if payload:
            return payload.decode("utf-8", errors="replace")
    return ""


def _fetch_attachment_payload(
    access_token: str,
    *,
    message_id: str,
    attachment_id: str,
) -> bytes:
    payload = _gmail_request(
        access_token,
        f"messages/{message_id}/attachments/{attachment_id}",
    )
    return _decode_message_part_body(payload)


def _collect_attachments(
    access_token: str,
    *,
    message_id: str,
    parts: list[dict[str, Any]],
) -> list[ExportAttachment]:
    attachments: list[ExportAttachment] = []
    for part in parts:
        filename = str(part.get("filename") or "").strip()
        if not filename:
            continue
        mime_type = str(part.get("mimeType") or "application/octet-stream").strip()
        body = part.get("body") or {}
        attachment_payload = _decode_message_part_body(body)
        attachment_id = str(body.get("attachmentId") or "").strip()
        if not attachment_payload and attachment_id:
            attachment_payload = _fetch_attachment_payload(
                access_token,
                message_id=message_id,
                attachment_id=attachment_id,
            )
        attachments.append(
            ExportAttachment(
                filename=filename,
                mime_type=mime_type,
                payload=attachment_payload,
            )
        )
    return attachments


def _build_export_message(
    access_token: str,
    *,
    message_payload: dict[str, Any],
    download_attachments: bool,
) -> ExportMessage:
    payload = message_payload.get("payload") or {}
    headers = payload.get("headers") or []
    parts = _walk_message_parts(payload)
    internal_date_ms = int(message_payload.get("internalDate") or 0)
    delivered_at = datetime.fromtimestamp(max(internal_date_ms, 0) / 1000, tz=UTC)
    attachments = (
        _collect_attachments(
            access_token,
            message_id=str(message_payload.get("id") or ""),
            parts=parts,
        )
        if download_attachments
        else []
    )
    return ExportMessage(
        gmail_message_id=str(message_payload.get("id") or "").strip(),
        thread_id=str(message_payload.get("threadId") or "").strip(),
        subject=_extract_header(headers, "Subject"),
        from_header=_extract_header(headers, "From"),
        to_header=_extract_header(headers, "To"),
        cc_header=_extract_header(headers, "Cc"),
        delivered_at=delivered_at,
        label_names=sorted(str(item).strip() for item in (message_payload.get("labelIds") or []) if str(item).strip()),
        snippet=str(message_payload.get("snippet") or "").strip(),
        body_text=_decode_part_text(parts, "text/plain"),
        body_html=_decode_part_text(parts, "text/html"),
        attachments=attachments,
    )


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_state(state_path: Path, payload: dict[str, Any]) -> None:
    state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _augment_query_for_incremental_export(base_query: str, last_internal_date_ms: int) -> str:
    if last_internal_date_ms <= 0:
        return base_query
    after_seconds = max((last_internal_date_ms // 1000) - 1, 0)
    query_parts = [part for part in [base_query.strip(), f"after:{after_seconds}"] if part]
    return " ".join(query_parts)


def run_export(
    *,
    account_email: str,
    authorized_user_file: Path,
    output_root: Path,
    query: str,
    max_results: int,
    download_attachments: bool,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / DEFAULT_STATE_FILENAME
    state = _load_state(state_path)
    authorized_user = _load_authorized_user_file(authorized_user_file)
    access_token = _refresh_access_token(authorized_user)
    _persist_authorized_user_file(authorized_user_file, authorized_user)

    profile = _gmail_request(access_token, "profile")
    profile_email = str(profile.get("emailAddress") or "").strip()
    if account_email and profile_email and account_email.lower() != profile_email.lower():
        raise ValueError(
            f"Authorized Gmail profile {profile_email} did not match expected account {account_email}."
        )

    effective_query = _augment_query_for_incremental_export(
        query,
        int(state.get("last_internal_date_ms") or 0),
    )

    exported = 0
    latest_internal_date_ms = int(state.get("last_internal_date_ms") or 0)
    next_page_token = ""
    while exported < max_results:
        remaining = max_results - exported
        page = _gmail_request(
            access_token,
            "messages",
            params={
                "maxResults": min(remaining, 500),
                "pageToken": next_page_token or None,
                "q": effective_query,
            },
        )
        messages = page.get("messages") or []
        if not isinstance(messages, list) or not messages:
            break
        for message_stub in messages:
            message_id = str((message_stub or {}).get("id") or "").strip()
            if not message_id:
                continue
            message_payload = _gmail_request(
                access_token,
                f"messages/{message_id}",
                params={"format": "full"},
            )
            internal_date_ms = int(message_payload.get("internalDate") or 0)
            latest_internal_date_ms = max(latest_internal_date_ms, internal_date_ms)
            export_message = _build_export_message(
                access_token,
                message_payload=message_payload,
                download_attachments=download_attachments,
            )
            write_export_message(
                output_root,
                export_message,
                download_attachments=download_attachments,
            )
            exported += 1
            if exported >= max_results:
                break
        next_page_token = str(page.get("nextPageToken") or "").strip()
        if not next_page_token:
            break

    state_payload = {
        "account_email": profile_email or account_email,
        "exported_at": datetime.now(UTC).isoformat(),
        "last_internal_date_ms": latest_internal_date_ms,
        "last_query": effective_query,
        "last_exported_count": exported,
    }
    _write_state(state_path, state_payload)
    return state_payload


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Gmail messages into a mirror folder.")
    parser.add_argument("--account-email", default="", help="Expected Gmail address for the authorized user.")
    parser.add_argument("--authorized-user-file", required=True, help="Path to a Gmail authorized-user JSON file.")
    parser.add_argument("--output-root", required=True, help="Directory where exported message markdown files should be written.")
    parser.add_argument("--query", default=DEFAULT_EXPORT_QUERY, help="Gmail search query for exported messages.")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS, help="Maximum number of messages to export in one run.")
    parser.add_argument("--download-attachments", action="store_true", help="Download Gmail attachments next to the exported markdown.")
    parser.add_argument("--skip-attachments", action="store_true", help="Do not download attachments even if the default is enabled.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    download_attachments = bool(args.download_attachments) and not bool(args.skip_attachments)
    try:
        result = run_export(
            account_email=str(args.account_email or "").strip(),
            authorized_user_file=Path(args.authorized_user_file).expanduser(),
            output_root=Path(args.output_root).expanduser(),
            query=str(args.query or DEFAULT_EXPORT_QUERY).strip(),
            max_results=max(int(args.max_results or DEFAULT_MAX_RESULTS), 1),
            download_attachments=download_attachments,
        )
    except (OSError, ValueError, error.URLError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False))
    return 0
