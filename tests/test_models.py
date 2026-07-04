from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import importlib.util

import pytest
from sqlalchemy import BigInteger
from sqlalchemy.exc import IntegrityError

from icloud_index_service.models.auth_session import AuthSession
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.models.job import Job
from icloud_index_service.models.base import Base
from icloud_index_service.models.change_set import ChangeSet
from icloud_index_service.models.change_set_item import ChangeSetItem
from icloud_index_service.models.cloud_vault_task import CloudVaultTask
from icloud_index_service.models.dedupe_group import DedupeGroup
from icloud_index_service.models.dedupe_group_item import DedupeGroupItem
from icloud_index_service.models.document_vault_note import DocumentVaultNote
from icloud_index_service.models.manual_feedback_event import ManualFeedbackEvent
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


def test_change_set_models_capture_reversible_history_relationships():
    assert ChangeSet.__table__.c.change_set_id.unique is True
    assert ChangeSet.__table__.c.status.nullable is False
    assert len(ChangeSetItem.__table__.c.change_set_id.foreign_keys) == 1
    assert (
        next(iter(ChangeSetItem.__table__.c.change_set_id.foreign_keys)).target_fullname
        == "change_sets.id"
    )


def test_document_vault_note_model_tracks_unique_relative_paths_and_source_links():
    relative_path_column = DocumentVaultNote.__table__.c.relative_path
    assert relative_path_column.unique is True
    assert DocumentVaultNote.__table__.c.visible_title.nullable is False
    assert len(DocumentVaultNote.__table__.c.source_file_record_id.foreign_keys) == 1


def test_manual_feedback_and_dedupe_models_capture_indexed_learning_and_candidates():
    assert ManualFeedbackEvent.__table__.c.event_id.unique is True
    assert len(ManualFeedbackEvent.__table__.c.note_id.foreign_keys) == 1
    assert CloudVaultTask.__table__.c.task_id.unique is True
    assert CloudVaultTask.__table__.c.status.nullable is False
    assert DedupeGroup.__table__.c.dedupe_group_id.unique is True
    assert DedupeGroup.__table__.c.status.nullable is False
    assert len(DedupeGroupItem.__table__.c.dedupe_group_id.foreign_keys) == 1
    assert (
        next(iter(DedupeGroupItem.__table__.c.dedupe_group_id.foreign_keys)).target_fullname
        == "dedupe_groups.id"
    )


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
    assert "Running upgrade 0003_file_sync_progress -> 0004_classification_jobs" in result.stdout
    assert "Running upgrade 0004_classification_jobs -> 0005_classification_retrieval_metadata" in result.stdout
    assert "last_seen_sync_run_id INTEGER" in result.stdout
    assert "CREATE TABLE classification_jobs" in result.stdout
    assert "CREATE TABLE classification_states" in result.stdout
    assert "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64);" in result.stdout
    assert "ALTER TABLE classification_states ADD COLUMN entity_summary TEXT;" in result.stdout
    assert "ROW_NUMBER() OVER" in result.stdout
    assert "Marked failed during 0002_active_refresh_unique_index migration" in result.stdout
    assert "Running upgrade 0005_classification_retrieval_metadata -> 0006_vault_mutation_index_tables" in result.stdout
    assert "CREATE TABLE change_sets" in result.stdout
    assert "CREATE TABLE change_set_items" in result.stdout
    assert "CREATE TABLE document_vault_notes" in result.stdout
    assert "Running upgrade 0006_vault_mutation_index_tables -> 0007_feedback_and_dedupe_index_tables" in result.stdout
    assert "CREATE TABLE manual_feedback_events" in result.stdout
    assert "CREATE TABLE dedupe_groups" in result.stdout
    assert "CREATE TABLE dedupe_group_items" in result.stdout
    assert "Running upgrade 0007_feedback_and_dedupe_index_tables -> 0008_cloud_vault_tasks" in result.stdout
    assert "CREATE TABLE cloud_vault_tasks" in result.stdout


def test_retrieval_metadata_migration_hardens_alembic_version_column_for_long_revision_ids():
    repo_root = Path(__file__).resolve().parents[1]
    migration_path = (
        repo_root / "migrations" / "versions" / "0005_classification_retrieval_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0005", migration_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    source_text = migration_path.read_text(encoding="utf-8")

    assert module.revision == "0005_classification_retrieval_metadata"
    assert len(module.revision) > 32
    assert 'op.alter_column(' in source_text
    assert '"alembic_version"' in source_text
    assert '"version_num"' in source_text
    assert "sa.String(length=64)" in source_text


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
