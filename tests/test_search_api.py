from __future__ import annotations

import json
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import icloud_index_service.main as main_module
from icloud_index_service.db import get_session
from icloud_index_service.models.classification_state import ClassificationState
from icloud_index_service.models.extracted_content import ExtractedContent
from icloud_index_service.models.file import FileRecord
from icloud_index_service.services.search_service import MAX_FILE_CONTENT_CHARS


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "task6.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    FileRecord.__table__.create(engine)
    ExtractedContent.__table__.create(engine)
    ClassificationState.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_indexed_file(
    session_factory: sessionmaker[Session],
    *,
    external_id: str = "file-1",
    name: str = "Budget.txt",
    path: str = "/Finance/Budget.txt",
    mime_type: str = "text/plain",
    content_text: str = "Quarterly budget numbers and forecasts",
    classification_state: dict[str, object] | None = None,
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
        if classification_state:
            session.add(
                ClassificationState(
                    file_id=file_record.id,
                    submission_status="completed",
                    **classification_state,
                )
            )
        session.commit()
        return file_record.id
    finally:
        session.close()


def _base_search_result(
    *,
    file_id: int,
    external_id: str,
    name: str,
    path: str,
    mime_type: str,
    excerpt: str,
    match_reasons: list[str],
) -> dict[str, object]:
    return {
        "file_id": file_id,
        "external_id": external_id,
        "name": name,
        "path": path,
        "mime_type": mime_type,
        "excerpt": excerpt,
        "primary_label": None,
        "summary": None,
        "confidence": None,
        "entity_summary": None,
        "topic_summary": None,
        "retrieval_terms": [],
        "classifier_note_path": None,
        "match_reasons": match_reasons,
    }


def _base_file_details(*, file_id: int, content_text: str, content_length: int, content_truncated: bool) -> dict[str, object]:
    return {
        "file_id": file_id,
        "external_id": "file-1",
        "name": "Budget.txt",
        "path": "/Finance/Budget.txt",
        "mime_type": "text/plain",
        "content_text": content_text,
        "content_length": content_length,
        "content_truncated": content_truncated,
        "excerpt": content_text[:280],
        "primary_label": None,
        "summary": None,
        "confidence": None,
        "entity_summary": None,
        "topic_summary": None,
        "retrieval_terms": [],
        "classifier_note_path": None,
    }


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
            _base_search_result(
                file_id=file_id,
                external_id="file-1",
                name="Budget.txt",
                path="/Finance/Budget.txt",
                mime_type="text/plain",
                excerpt="Quarterly budget numbers and forecasts",
                match_reasons=["name", "path", "content"],
            )
        ],
    }


def test_search_endpoint_respects_path_scope(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    finance_file_id = _seed_indexed_file(
        session_factory,
        external_id="finance-file",
        name="Budget.txt",
        path="/Finance/Budget.txt",
        content_text="Finance budget notes",
    )
    _seed_indexed_file(
        session_factory,
        external_id="personal-file",
        name="Budget.txt",
        path="/Personal/Budget.txt",
        content_text="Personal budget notes",
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
            response = client.get(
                "/search",
                params={"query": "budget", "limit": 5, "path_scope": "/Finance"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "query": "budget",
        "limit": 5,
        "path_scope": "/Finance",
        "results": [
            _base_search_result(
                file_id=finance_file_id,
                external_id="finance-file",
                name="Budget.txt",
                path="/Finance/Budget.txt",
                mime_type="text/plain",
                excerpt="Finance budget notes",
                match_reasons=["name", "path", "content"],
            )
        ],
    }


def test_search_endpoint_accepts_relative_path_scope(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    finance_file_id = _seed_indexed_file(
        session_factory,
        external_id="finance-file",
        name="Budget.txt",
        path="/Finance/Budget.txt",
        content_text="Finance budget notes",
    )
    _seed_indexed_file(
        session_factory,
        external_id="personal-file",
        name="Budget.txt",
        path="/Personal/Budget.txt",
        content_text="Personal budget notes",
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
            response = client.get(
                "/search",
                params={"query": "budget", "limit": 5, "path_scope": "Finance"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "query": "budget",
        "limit": 5,
        "path_scope": "Finance",
        "results": [
            _base_search_result(
                file_id=finance_file_id,
                external_id="finance-file",
                name="Budget.txt",
                path="/Finance/Budget.txt",
                mime_type="text/plain",
                excerpt="Finance budget notes",
                match_reasons=["name", "path", "content"],
            )
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
    assert response.json() == _base_file_details(
        file_id=file_id,
        content_text="Quarterly budget numbers and forecasts",
        content_length=38,
        content_truncated=False,
    )


def test_file_endpoint_caps_large_content_payloads(tmp_path, monkeypatch):
    session_factory = _build_session_factory(tmp_path)
    source_text = "A" * (MAX_FILE_CONTENT_CHARS + 25)
    file_id = _seed_indexed_file(
        session_factory,
        content_text=source_text,
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
            response = client.get(f"/files/{file_id}")
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == _base_file_details(
        file_id=file_id,
        content_text="A" * MAX_FILE_CONTENT_CHARS,
        content_length=MAX_FILE_CONTENT_CHARS + 25,
        content_truncated=True,
    )


def test_file_note_and_source_endpoints_return_vault_and_source_metadata(tmp_path, monkeypatch):
    vault_root = tmp_path / "document-vault"
    note_path = vault_root / "01 Classified" / "financial" / "Budget - financial.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'canonical_source_path: "/srv/cloud-vault/mirrors/google1/Finance/Budget.txt"',
                'source_link: "[Budget.txt](file://192.168.50.86/cloud-vault/mirrors/google1/Finance/Budget.txt)"',
                'attachment_mode: "canonical-source-link"',
                "---",
                "",
                "# Budget",
                "",
                "Quarterly budget note body.",
            ]
        ),
        encoding="utf-8",
    )

    source_root = tmp_path / "mirrors"
    source_path = source_root / "google1" / "Finance" / "Budget.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("Budget source body", encoding="utf-8")

    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(
        session_factory,
        external_id="budget-file",
        name="Budget.txt",
        path="/google1/Finance/Budget.txt",
        content_text="Budget source body",
        classification_state={
            "classifier_note_path": "/vault/01 Classified/financial/Budget - financial.md",
            "primary_label": "financial",
            "classifier_manifest_record": json.dumps(
                {
                    "canonical_source_path": str(source_path),
                    "source_link": "[Budget.txt](file://192.168.50.86/cloud-vault/mirrors/google1/Finance/Budget.txt)",
                    "attachment_mode": "canonical-source-link",
                }
            ),
        },
    )

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(source_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            note_response = client.get(f"/files/{file_id}/note")
            source_response = client.get(f"/files/{file_id}/source")
    finally:
        main_module.app.dependency_overrides.clear()

    assert note_response.status_code == 200
    assert note_response.json()["note_available"] is True
    assert note_response.json()["note_relative_path"] == "01 Classified/financial/Budget - financial.md"
    assert "Quarterly budget note body." in note_response.json()["note_content"]
    assert note_response.json()["canonical_source_path"] == str(source_path)

    assert source_response.status_code == 200
    assert source_response.json()["source_exists"] is True
    assert source_response.json()["canonical_source_path"] == str(source_path)
    assert source_response.json()["download_path"] == f"/files/{file_id}/source/download"


def test_search_bundles_endpoint_returns_hydrated_note_and_source_payloads(tmp_path, monkeypatch):
    vault_root = tmp_path / "document-vault"
    note_path = vault_root / "01 Classified" / "medical" / "appeals" / "Appeal - medical - appeals.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "\n".join(
            [
                "---",
                'canonical_source_path: "/srv/cloud-vault/mirrors/google1/Appeal.docx"',
                'source_link: "[Appeal.docx](file://192.168.50.86/cloud-vault/mirrors/google1/Appeal.docx)"',
                'attachment_mode: "canonical-source-link"',
                "---",
                "",
                "# Appeal",
                "",
                "Appeal note body for bundle search.",
            ]
        ),
        encoding="utf-8",
    )

    source_root = tmp_path / "mirrors"
    source_path = source_root / "google1" / "Appeal.docx"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("A" * 20, encoding="utf-8")

    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(
        session_factory,
        external_id="appeal-file",
        name="Appeal.docx",
        path="/google1/Appeal.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content_text="A" * 20,
        classification_state={
            "classifier_note_path": "/vault/01 Classified/medical/appeals/Appeal - medical - appeals.md",
            "primary_label": "medical",
            "classifier_manifest_record": json.dumps(
                {
                    "canonical_source_path": str(source_path),
                    "source_link": "[Appeal.docx](file://192.168.50.86/cloud-vault/mirrors/google1/Appeal.docx)",
                    "attachment_mode": "canonical-source-link",
                }
            ),
        },
    )

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(source_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            response = client.get(
                "/search/bundles",
                params={
                    "query": "Appeal",
                    "limit": 5,
                    "path_scope": "/google1",
                    "hydrate_limit": 1,
                    "max_chars": 12,
                    "note_max_chars": 10,
                },
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "Appeal"
    assert payload["path_scope"] == "/google1"
    assert payload["hydrate_limit"] == 1
    assert payload["hydrated_count"] == 1
    assert payload["results"][0]["file_id"] == file_id
    assert len(payload["bundles"]) == 1
    bundle = payload["bundles"][0]
    assert bundle["match"] == (
        _base_search_result(
            file_id=file_id,
            external_id="appeal-file",
            name="Appeal.docx",
            path="/google1/Appeal.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            excerpt="AAAAAAAAAAAAAAAAAAAA",
            match_reasons=["name", "path"],
        )
        | {
            "primary_label": "medical",
            "classifier_note_path": "/vault/01 Classified/medical/appeals/Appeal - medical - appeals.md",
        }
    )
    assert bundle["file"]["content_text"] == "AAAAAAAAAAAA"
    assert bundle["file"]["content_truncated"] is True
    assert bundle["file"]["primary_label"] == "medical"
    assert bundle["note"]["note_available"] is True
    assert bundle["note"]["note_content"] == "---\ncanoni"
    assert bundle["note"]["note_truncated"] is True
    assert "Appeal note body for bundle search." in bundle["note"]["note_excerpt"]
    assert bundle["note"]["canonical_source_path"] == str(source_path)
    assert bundle["source"]["canonical_source_path"] == str(source_path)
    assert bundle["source"]["source_exists"] is True
    assert bundle["source"]["download_path"] == f"/files/{file_id}/source/download"


def test_file_source_download_endpoint_streams_original_file(tmp_path, monkeypatch):
    source_root = tmp_path / "mirrors"
    source_path = source_root / "icloud" / "Scanned" / "botox.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"pdf-bytes")

    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(
        session_factory,
        external_id="botox-file",
        name="botox.pdf",
        path="/icloud/Scanned/botox.pdf",
        content_text="botox text",
        classification_state={
            "classifier_manifest_record": json.dumps(
                {
                    "canonical_source_path": str(source_path),
                    "attachment_mode": "canonical-source-link",
                }
            ),
        },
    )

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(source_root))
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            response = client.get(f"/files/{file_id}/source/download")
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"pdf-bytes"
    assert response.headers["cache-control"] == "private, no-store"


def test_search_and_file_endpoints_require_bearer_auth_when_plugin_token_is_set(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path)
    file_id = _seed_indexed_file(session_factory)

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("PLUGIN_API_TOKEN", "secret-token")
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    main_module.app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(main_module.app) as client:
            unauthorized_search = client.get("/search", params={"query": "budget", "limit": 5})
            authorized_search = client.get(
                "/search",
                params={"query": "budget", "limit": 5},
                headers={"Authorization": "Bearer secret-token"},
            )
            unauthorized_file = client.get(f"/files/{file_id}")
            authorized_file = client.get(
                f"/files/{file_id}",
                headers={"Authorization": "Bearer secret-token"},
            )
    finally:
        main_module.app.dependency_overrides.clear()

    assert unauthorized_search.status_code == 401
    assert authorized_search.status_code == 200
    assert unauthorized_file.status_code == 401
    assert authorized_file.status_code == 200


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
        _base_search_result(
            file_id=percent_file_id,
            external_id="percent-file",
            name="100% Plan.txt",
            path="/Finance/100% Plan.txt",
            mime_type="text/plain",
            excerpt="Percent-heavy budget notes",
            match_reasons=["name", "path"],
        )
    ]
    assert underscore_response.status_code == 200
    assert underscore_response.json()["results"] == [
        _base_search_result(
            file_id=underscore_file_id,
            external_id="underscore-file",
            name="Q1_budget.txt",
            path="/Finance/Q1_budget.txt",
            mime_type="text/plain",
            excerpt="Underscore-heavy budget notes",
            match_reasons=["name", "path"],
        )
    ]


def test_search_endpoint_uses_entity_and_topic_metadata_to_find_misfiled_documents(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path)
    matched_file_id = _seed_indexed_file(
        session_factory,
        external_id="appeal-file",
        name="scan-001.txt",
        path="/Misc/scan-001.txt",
        content_text="Scanned correspondence with sparse OCR.",
        classification_state={
            "primary_label": "medical",
            "summary": "Insurance appeal packet.",
            "entity_summary": "organizations: Aetna Life Insurance Company; identifiers: claim id: EDPDK70ZX00",
            "topic_summary": "medical, insurance, legal, appeal",
            "retrieval_terms_json": '["aetna", "appeal", "claim id", "insurance"]',
            "retrieval_text": "Aetna appeal claim packet for insurance review.",
        },
    )
    _seed_indexed_file(
        session_factory,
        external_id="other-file",
        name="Random.txt",
        path="/Misc/Random.txt",
        content_text="Unrelated household notes.",
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
            response = client.get("/search", params={"query": "Aetna appeal", "limit": 5})
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["file_id"] == matched_file_id
    assert payload["results"][0]["primary_label"] == "medical"
    assert "aetna" in [term.lower() for term in payload["results"][0]["retrieval_terms"]]
    assert "entities" in payload["results"][0]["match_reasons"]


def test_search_endpoint_hides_underscore_prefixed_paths_from_normal_discovery(
    tmp_path,
    monkeypatch,
):
    session_factory = _build_session_factory(tmp_path)
    _seed_indexed_file(
        session_factory,
        external_id="hidden-file",
        name="Appeal.txt",
        path="/google1/_CHANGES_BACKUP/Appeal.txt",
        content_text="Hidden appeal notes",
    )
    visible_file_id = _seed_indexed_file(
        session_factory,
        external_id="visible-file",
        name="Appeal.txt",
        path="/google1/Inbox/Appeal.txt",
        content_text="Visible appeal notes",
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
            response = client.get("/search", params={"query": "Appeal", "limit": 10})
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["results"] == [
        _base_search_result(
            file_id=visible_file_id,
            external_id="visible-file",
            name="Appeal.txt",
            path="/google1/Inbox/Appeal.txt",
            mime_type="text/plain",
            excerpt="Visible appeal notes",
            match_reasons=["name", "path", "content"],
        )
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
        _base_search_result(
            file_id=file_id,
            external_id="file-1",
            name="Budget.txt",
            path="/Finance/Budget.txt",
            mime_type="text/plain",
            excerpt="Quarterly budget numbers and forecasts",
            match_reasons=["name", "path", "content"],
        )
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
