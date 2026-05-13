from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import BigInteger
from sqlalchemy.exc import IntegrityError

from icloud_index_service.models.auth_session import AuthSession
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.job import Job
from icloud_index_service.models.base import Base
from icloud_index_service.models.sync_run import SyncRun


def _alembic_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_USER": "icloud",
            "POSTGRES_PASSWORD": "secret",
            "POSTGRES_HOST": "db",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "icloud_index",
        }
    )
    env.update(overrides)
    return env


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
    assert size_column.server_default is None


def test_file_record_tracks_last_seen_sync_run_for_resumable_snapshots():
    last_seen_column = FileRecord.__table__.c.last_seen_sync_run_id

    assert last_seen_column.nullable is True
    assert len(last_seen_column.foreign_keys) == 1
    assert next(iter(last_seen_column.foreign_keys)).target_fullname == "sync_runs.id"


def test_file_record_exposes_matching_server_default_for_is_deleted():
    is_deleted_column = FileRecord.__table__.c.is_deleted

    assert is_deleted_column.server_default is not None
    assert "false" in str(is_deleted_column.server_default.arg).lower()


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


def test_job_model_declares_single_active_metadata_refresh_index():
    job_table = Job.__table__
    partial_indexes = {
        index.name: index for index in job_table.indexes if index.unique
    }

    assert "uq_jobs_active_metadata_refresh" in partial_indexes
    assert [column.name for column in partial_indexes["uq_jobs_active_metadata_refresh"].columns] == [
        "job_type"
    ]


def test_job_schema_enforces_single_active_metadata_refresh(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    database_path = tmp_path / "task5-models.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Job(
                job_type="metadata-refresh",
                status="queued",
            )
        )
        session.commit()

        session.add(
            Job(
                job_type="metadata-refresh",
                status="running",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_initial_migration_captures_authoritative_schema_rules():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=repo_root,
        env=_alembic_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "is_deleted BOOLEAN DEFAULT false NOT NULL" in result.stdout
    assert "size_bytes BIGINT" in result.stdout
    assert "UNIQUE (file_id)" in result.stdout
    assert "UNIQUE (account_identifier)" in result.stdout
    assert "UNIQUE (dsid)" in result.stdout
    assert "refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in result.stdout
    assert "CREATE UNIQUE INDEX uq_jobs_active_metadata_refresh" in result.stdout
    assert "Running upgrade 0001_initial_schema -> 0002_active_refresh_unique_index" in result.stdout
    assert "Running upgrade 0002_active_refresh_unique_index -> 0003_file_sync_progress" in result.stdout
    assert "last_seen_sync_run_id INTEGER" in result.stdout
    assert "ROW_NUMBER() OVER" in result.stdout
    assert "Marked failed during 0002_active_refresh_unique_index migration" in result.stdout


def test_alembic_upgrade_sql_fails_fast_without_database_settings():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()

    for key in [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    ]:
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0


def test_alembic_upgrade_sql_supports_percent_encoded_database_url():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=repo_root,
        env=_alembic_env(
            POSTGRES_USER="icloud:user",
            POSTGRES_PASSWORD="se/cret:@value",
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "CREATE TABLE files" in result.stdout
