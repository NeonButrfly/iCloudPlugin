from fastapi.testclient import TestClient

import icloud_index_service.main as main_module
from icloud_index_service.services.auth_session_manager import (
    build_auth_status_payload,
    redact_cookie_value,
)


def test_redact_cookie_value_masks_interior_characters():
    assert redact_cookie_value("abcdef123456") == "ab********56"


def test_redact_cookie_value_fully_masks_short_secrets():
    assert redact_cookie_value("abc123") == "******"


def test_build_auth_status_payload_can_reflect_current_session_state():
    assert build_auth_status_payload(
        session_state="authenticated",
        database_state="ok",
    ) == {"status": "authenticated", "database": "ok"}


def test_auth_status_endpoint_reports_needs_bootstrap_when_startup_validation_succeeds(monkeypatch):
    validation_calls: list[str] = []

    def fake_validate_database_configuration() -> None:
        validation_calls.append("validated")

    monkeypatch.setattr(
        main_module,
        "validate_database_configuration",
        fake_validate_database_configuration,
    )
    with TestClient(main_module.app) as client:
        response = client.get("/auth/status")

    assert response.status_code == 200
    assert response.json() == build_auth_status_payload(database_state="ok")
    assert validation_calls == ["validated"]


def test_auth_status_endpoint_stays_reachable_when_startup_validation_fails(monkeypatch):
    validation_calls: list[str] = []

    def fake_validate_database_configuration() -> None:
        validation_calls.append("validated")
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        main_module,
        "validate_database_configuration",
        fake_validate_database_configuration,
    )
    with TestClient(main_module.app) as client:
        response = client.get("/auth/status")

    assert response.status_code == 200
    assert response.json() == build_auth_status_payload(database_state="unavailable")
    assert validation_calls == ["validated"]
