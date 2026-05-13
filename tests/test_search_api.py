from __future__ import annotations

from pathlib import Path

from fastapi import Request
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


def _seed_indexed_file(
    session_factory: sessionmaker[Session],
    *,
    external_id: str = "file-1",
    name: str = "Budget.txt",
    path: str = "/Finance/Budget.txt",
    mime_type: str = "text/plain",
    content_text: str = "Quarterly budget numbers and forecasts",
) -> int:
    session = session_factory()
    try:
        file_record = FileRecord(
            external_id=external_id,
            name=name,
            path=path,
            mime_type=mime_type,
            size_bytes=24,
        )
        session.add(file_record)
        session.commit()
        session.refresh(file_record)
        session.add(
            ExtractedContent(
                file_id=file_record.id,
                content_text=content_text,
                content_hash=f"hash-{external_id}",
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


def test_search_endpoint_treats_percent_and_underscore_as_literal_query_characters(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path)
    percent_file_id = _seed_indexed_file(
        session_factory,
        external_id="percent-file",
        name="100% Plan.txt",
        path="/Finance/100% Plan.txt",
        content_text="Percent-heavy budget notes",
    )
    underscore_file_id = _seed_indexed_file(
        session_factory,
        external_id="underscore-file",
        name="Q1_budget.txt",
        path="/Finance/Q1_budget.txt",
        content_text="Underscore-heavy budget notes",
    )
    _seed_indexed_file(
        session_factory,
        external_id="plain-file",
        name="OrdinaryBudget.txt",
        path="/Finance/OrdinaryBudget.txt",
        content_text="Plain budget notes",
    )

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
            percent_response = client.get("/search", params={"query": "%", "limit": 10})
            underscore_response = client.get("/search", params={"query": "_", "limit": 10})
    finally:
        main_module.app.dependency_overrides.clear()

    assert percent_response.status_code == 200
    assert percent_response.json()["results"] == [
        {
            "file_id": percent_file_id,
            "external_id": "percent-file",
            "name": "100% Plan.txt",
            "path": "/Finance/100% Plan.txt",
            "mime_type": "text/plain",
            "excerpt": "Percent-heavy budget notes",
        }
    ]
    assert underscore_response.status_code == 200
    assert underscore_response.json()["results"] == [
        {
            "file_id": underscore_file_id,
            "external_id": "underscore-file",
            "name": "Q1_budget.txt",
            "path": "/Finance/Q1_budget.txt",
            "mime_type": "text/plain",
            "excerpt": "Underscore-heavy budget notes",
        }
    ]


def test_search_endpoint_reports_controlled_degraded_response_when_database_is_unavailable(
    monkeypatch,
):
    def fake_validate_database_configuration() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        main_module,
        "validate_database_configuration",
        fake_validate_database_configuration,
    )
    monkeypatch.setattr(main_module, "check_database_health", lambda: False)

    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        response = client.get("/search", params={"query": "budget", "limit": 5})

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "status": "degraded",
            "database": "unavailable",
            "operation": "search",
            "startup_validation_error": "RuntimeError: database unavailable",
        }
    }


def test_file_endpoint_reports_controlled_degraded_response_when_database_is_unavailable(
    monkeypatch,
):
    def fake_validate_database_configuration() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        main_module,
        "validate_database_configuration",
        fake_validate_database_configuration,
    )
    monkeypatch.setattr(main_module, "check_database_health", lambda: False)

    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        response = client.get("/files/1")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "status": "degraded",
            "database": "unavailable",
            "operation": "files",
            "startup_validation_error": "RuntimeError: database unavailable",
        }
    }


def test_search_and_file_endpoints_accept_plain_session_dependency_overrides(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(session_factory)
    plain_session = session_factory()
    close_calls = 0
    real_close = plain_session.close

    def counting_close() -> None:
        nonlocal close_calls
        close_calls += 1
        real_close()

    monkeypatch.setattr(plain_session, "close", counting_close)

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = lambda: plain_session

    try:
        with TestClient(main_module.app) as client:
            search_response = client.get("/search", params={"query": "budget", "limit": 5})
            file_response = client.get(f"/files/{file_id}")
    finally:
        main_module.app.dependency_overrides.clear()
        real_close()

    assert search_response.status_code == 200
    assert search_response.json()["results"] == [
        {
            "file_id": file_id,
            "external_id": "file-1",
            "name": "Budget.txt",
            "path": "/Finance/Budget.txt",
            "mime_type": "text/plain",
            "excerpt": "Quarterly budget numbers and forecasts",
        }
    ]
    assert file_response.status_code == 200
    assert file_response.json()["file_id"] == file_id
    assert close_calls == 2


def test_search_and_file_endpoints_accept_request_aware_dependency_overrides(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(session_factory)
    opened_sessions: list[Session] = []
    opened_real_closes: list[object] = []
    seen_paths: list[str] = []
    close_calls = 0

    def override_get_session(request: Request) -> Session:
        nonlocal close_calls
        seen_paths.append(request.url.path)
        session = session_factory()
        real_close = session.close

        def counting_close() -> None:
            nonlocal close_calls
            close_calls += 1
            real_close()

        monkeypatch.setattr(session, "close", counting_close)
        opened_sessions.append(session)
        opened_real_closes.append(real_close)
        return session

    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            search_response = client.get("/search", params={"query": "budget", "limit": 5})
            file_response = client.get(f"/files/{file_id}")
    finally:
        main_module.app.dependency_overrides.clear()
        for real_close in opened_real_closes:
            real_close()

    assert search_response.status_code == 200
    assert file_response.status_code == 200
    assert seen_paths == ["/search", f"/files/{file_id}"]
    assert close_calls == 2
