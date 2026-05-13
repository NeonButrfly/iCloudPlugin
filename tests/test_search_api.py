from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import icloud_index_service.main as main_module
from icloud_index_service.db import get_session
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "task6.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    FileRecord.__table__.create(engine)
    ExtractedContent.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_indexed_file(session_factory: sessionmaker[Session]) -> int:
    session = session_factory()
    try:
        file_record = FileRecord(
            external_id="file-1",
            name="Budget.txt",
            path="/Finance/Budget.txt",
            mime_type="text/plain",
            size_bytes=24,
        )
        session.add(file_record)
        session.commit()
        session.refresh(file_record)
        session.add(
            ExtractedContent(
                file_id=file_record.id,
                content_text="Quarterly budget numbers and forecasts",
                content_hash="hash-1",
            )
        )
        session.commit()
        return file_record.id
    finally:
        session.close()


def test_search_endpoint_returns_matching_file_excerpt(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(session_factory)

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            response = client.get("/search", params={"query": "budget", "limit": 5})
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "query": "budget",
        "limit": 5,
        "results": [
            {
                "file_id": file_id,
                "external_id": "file-1",
                "name": "Budget.txt",
                "path": "/Finance/Budget.txt",
                "mime_type": "text/plain",
                "excerpt": "Quarterly budget numbers and forecasts",
            }
        ],
    }


def test_file_endpoint_returns_indexed_file_details(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(session_factory)

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            response = client.get(f"/files/{file_id}")
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "file_id": file_id,
        "external_id": "file-1",
        "name": "Budget.txt",
        "path": "/Finance/Budget.txt",
        "mime_type": "text/plain",
        "content_text": "Quarterly budget numbers and forecasts",
        "excerpt": "Quarterly budget numbers and forecasts",
    }
