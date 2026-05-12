import pytest

from icloud_index_service.config import get_settings


@pytest.fixture(autouse=True)
def clear_cached_service_config():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
