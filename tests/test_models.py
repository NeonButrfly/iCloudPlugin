from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import BigInteger

from icloud_index_service.models.auth_session import AuthSession
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.sync_run import SyncRun


def test_file_record_defaults_to_active():
    record = FileRecord(
        external_id="file-123",
        name="notes.md",
        path="/Work/notes.md",
        mime_type="text/markdown",
    )

    assert record.is_deleted is False


def test_file_record_uses_bigint_for_multi_gb_sizes():
    size_column = FileRecord.__table__.c.size_bytes

    assert isinstance(size_column.type, BigInteger)
    assert size_column.nullable is True


def test_extracted_content_enforces_one_authoritative_row_per_file():
    file_id_column = ExtractedContent.__table__.c.file_id

    assert file_id_column.unique is True
    assert file_id_column.nullable is False


def test_auth_session_metadata_identifies_authoritative_session_per_account():
    table = AuthSession.__table__

    assert table.c.account_identifier.unique is True
    assert table.c.dsid.unique is True
    assert table.c.refreshed_at.nullable is False


def test_timestamp_models_expose_matching_server_defaults():
    timestamp_columns = [
        SyncRun.__table__.c.started_at,
        ExtractedContent.__table__.c.extracted_at,
        AuthSession.__table__.c.refreshed_at,
    ]

    for column in timestamp_columns:
        assert column.server_default is not None
        assert "now()" in str(column.server_default.arg)


def test_initial_migration_captures_authoritative_schema_rules():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["python", "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "size_bytes BIGINT" in result.stdout
    assert "UNIQUE (file_id)" in result.stdout
    assert "UNIQUE (account_identifier)" in result.stdout
    assert "UNIQUE (dsid)" in result.stdout
    assert "refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in result.stdout
