from __future__ import annotations

from datetime import UTC, datetime

from icloud_index_service.services.gmail_export import ExportAttachment
from icloud_index_service.services.gmail_export import ExportMessage
from icloud_index_service.services.gmail_export import build_export_file_path
from icloud_index_service.services.gmail_export import write_export_message


def test_build_export_file_path_uses_timestamp_subject_and_message_id(tmp_path):
    message = ExportMessage(
        gmail_message_id="186abc",
        thread_id="thread-1",
        subject="Appeal / Update",
        from_header="sender@example.com",
        to_header="kaymayers9@gmail.com",
        cc_header="",
        delivered_at=datetime(2026, 7, 7, 18, 45, 30, tzinfo=UTC),
        label_names=["INBOX", "IMPORTANT"],
        snippet="Appeal update",
        body_text="Hello world",
        body_html="",
        attachments=[],
    )

    export_path = build_export_file_path(tmp_path, message)

    assert export_path == tmp_path / "2026" / "07" / "2026-07-07T184530Z--Appeal-Update--186abc.md"


def test_write_export_message_persists_markdown_and_attachments(tmp_path):
    message = ExportMessage(
        gmail_message_id="186xyz",
        thread_id="thread-9",
        subject="Coverage Decision",
        from_header="case@example.com",
        to_header="keifmayers@gmail.com",
        cc_header="review@example.com",
        delivered_at=datetime(2026, 7, 6, 9, 30, 0, tzinfo=UTC),
        label_names=["INBOX", "STARRED"],
        snippet="Coverage decision attached",
        body_text="The attached decision is ready for review.",
        body_html="<p>The attached decision is ready for review.</p>",
        attachments=[
            ExportAttachment(
                filename="decision.txt",
                mime_type="text/plain",
                payload=b"decision body",
            )
        ],
    )

    export_path = write_export_message(tmp_path, message, download_attachments=True)

    assert export_path.exists()
    markdown = export_path.read_text(encoding="utf-8")
    assert "thread_id: thread-9" in markdown
    assert "from: case@example.com" in markdown
    assert "to: keifmayers@gmail.com" in markdown
    assert "labels:" in markdown
    assert "Coverage decision attached" in markdown
    assert "decision.txt" in markdown

    attachment_path = export_path.parent / f"{export_path.stem}.attachments" / "decision.txt"
    assert attachment_path.read_text(encoding="utf-8") == "decision body"


def test_write_export_message_sanitizes_attachment_filenames(tmp_path):
    message = ExportMessage(
        gmail_message_id="186safe",
        thread_id="thread-safe",
        subject="Attachment Paths",
        from_header="case@example.com",
        to_header="keifmayers@gmail.com",
        cc_header="",
        delivered_at=datetime(2026, 7, 6, 9, 30, 0, tzinfo=UTC),
        label_names=["INBOX"],
        snippet="nested attachment",
        body_text="Attachment test",
        body_html="",
        attachments=[
            ExportAttachment(
                filename="../unsafe/decision.txt",
                mime_type="text/plain",
                payload=b"safe body",
            )
        ],
    )

    export_path = write_export_message(tmp_path, message, download_attachments=True)

    attachment_path = export_path.parent / f"{export_path.stem}.attachments" / "decision.txt"
    assert attachment_path.read_text(encoding="utf-8") == "safe body"
    assert not (export_path.parent / f"{export_path.stem}.attachments" / ".." / "unsafe").exists()
