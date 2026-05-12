from icloud_index_service.models.file import FileRecord


def test_file_record_defaults_to_active():
    record = FileRecord(
        external_id="file-123",
        name="notes.md",
        path="/Work/notes.md",
        mime_type="text/markdown",
    )

    assert record.is_deleted is False
