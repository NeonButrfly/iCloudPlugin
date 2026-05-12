import pytest

from icloud_index_service.db import clear_database_caches


@pytest.fixture(autouse=True)
def clear_cached_service_config(monkeypatch):
    monkeypatch.setenv("ICLOUD_INDEX_SKIP_DB_STARTUP_VALIDATION", "1")
    clear_database_caches()
    yield
    clear_database_caches()
