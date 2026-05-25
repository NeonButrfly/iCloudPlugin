from fastapi.testclient import TestClient

import icloud_index_service.main as main_module
from icloud_index_service.services.auth_session_manager import (
    build_auth_status_payload,
    detect_auth_session_state,
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
        startup_validation_error="RuntimeError: database unavailable",
    ) == {
        "status": "authenticated",
        "database": "ok",
        "startup_validation_error": "RuntimeError: database unavailable",
    }


def test_detect_auth_session_state_requires_credentials(monkeypatch):
    monkeypatch.delenv("ICLOUD_APPLE_ID", raising=False)
    monkeypatch.delenv("ICLOUD_APPLE_PASSWORD", raising=False)

    assert detect_auth_session_state() == "needs-bootstrap"


def test_detect_auth_session_state_reports_configured_when_credentials_exist(monkeypatch):
    monkeypatch.setenv("ICLOUD_APPLE_ID", "user@example.com")
    monkeypatch.setenv("ICLOUD_APPLE_PASSWORD", "secret")

    assert detect_auth_session_state() == "configured"


def test_detect_auth_session_state_reports_configured_for_filesystem_mirror_mode(
    monkeypatch,
):
    monkeypatch.setenv("ICLOUD_SOURCE_MODE", "filesystem-mirror")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", "/srv/cloud-vault/mirrors")
    monkeypatch.delenv("ICLOUD_APPLE_ID", raising=False)
    monkeypatch.delenv("ICLOUD_APPLE_PASSWORD", raising=False)

    assert detect_auth_session_state() == "configured"


def test_auth_status_endpoint_reports_needs_bootstrap_when_startup_validation_succeeds(monkeypatch):
    validation_calls: list[str] = []

    def fake_validate_database_configuration() -> None:
        validation_calls.append("validated")

    monkeypatch.setattr(
        main_module,
        "validate_database_configuration",
        fake_validate_database_configuration,
    )
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    with TestClient(main_module.app) as client:
        response = client.get("/auth/status")

    assert response.status_code == 200
    assert response.json() == build_auth_status_payload(database_state="ok")
    assert validation_calls == ["validated"]


def test_auth_status_endpoint_reports_current_database_reachability(monkeypatch):
    monkeypatch.setattr(main_module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(main_module, "check_database_health", lambda: False)

    with TestClient(main_module.app) as client:
        response = client.get("/auth/status")

    assert response.status_code == 200
    assert response.json() == build_auth_status_payload(database_state="unavailable")


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
    monkeypatch.setattr(main_module, "check_database_health", lambda: False)
    with TestClient(main_module.app) as client:
        response = client.get("/auth/status")

    assert response.status_code == 200
    assert response.json() == build_auth_status_payload(
        database_state="unavailable",
        startup_validation_error="RuntimeError: database unavailable",
    )
    assert validation_calls == ["validated"]


def test_auth_status_endpoint_suppresses_startup_error_after_live_database_recovery(monkeypatch):
    validation_calls: list[str] = []

    def fake_validate_database_configuration() -> None:
        validation_calls.append("validated")
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        main_module,
        "validate_database_configuration",
        fake_validate_database_configuration,
    )
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    with TestClient(main_module.app) as client:
        response = client.get("/auth/status")

    assert response.status_code == 200
    assert response.json() == build_auth_status_payload(database_state="ok")
    assert validation_calls == ["validated"]
