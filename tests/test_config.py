import importlib
import json
import subprocess
import sys
import types
from pathlib import Path

from icloud_index_service.config import Settings, get_settings


def _load_db_module_with_fake_sqlalchemy(monkeypatch):
    created_urls: list[str] = []

    fake_sqlalchemy = types.ModuleType("sqlalchemy")

    def fake_create_engine(url: str, pool_pre_ping: bool = True):
        engine = {"url": url, "pool_pre_ping": pool_pre_ping}
        created_urls.append(url)
        return engine

    fake_sqlalchemy.Engine = dict
    fake_sqlalchemy.create_engine = fake_create_engine

    fake_sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")

    class FakeSession:
        pass

    def fake_sessionmaker(**kwargs):
        return {"bind": kwargs["bind"], "options": kwargs}

    fake_sqlalchemy_orm.Session = FakeSession
    fake_sqlalchemy_orm.sessionmaker = fake_sessionmaker

    monkeypatch.setitem(sys.modules, "sqlalchemy", fake_sqlalchemy)
    monkeypatch.setitem(sys.modules, "sqlalchemy.orm", fake_sqlalchemy_orm)

    import icloud_index_service.db as db_module

    db_module = importlib.reload(db_module)
    return db_module, created_urls


def test_settings_build_database_url():
    settings = Settings(
        postgres_user="icloud:user",
        postgres_password="se/cret:@value",
        postgres_host="db",
        postgres_port=5432,
        postgres_db="icloud_index",
    )

    assert (
        settings.database_url
        == "postgresql+psycopg://icloud%3Auser:se%2Fcret%3A%40value@db:5432/icloud_index"
    )


def test_get_settings_loads_database_config_from_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "env-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env-pass")
    monkeypatch.setenv("POSTGRES_HOST", "env-host")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "env-db")

    settings = get_settings()

    assert settings.postgres_user == "env-user"
    assert settings.postgres_password == "env-pass"
    assert settings.postgres_host == "env-host"
    assert settings.postgres_port == 6543
    assert settings.postgres_db == "env-db"


def test_clear_database_caches_rebuilds_engine_for_updated_environment(monkeypatch):
    db_module, created_urls = _load_db_module_with_fake_sqlalchemy(monkeypatch)

    monkeypatch.setenv("POSTGRES_USER", "icloud")
    monkeypatch.setenv("POSTGRES_PASSWORD", "first-pass")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "icloud_index")

    db_module.clear_database_caches()
    first_engine = db_module.get_engine()
    first_session_factory = db_module.get_session_factory()

    monkeypatch.setenv("POSTGRES_PASSWORD", "next/pass")
    monkeypatch.setenv("POSTGRES_DB", "icloud_index_v2")

    db_module.clear_database_caches()
    second_engine = db_module.get_engine()
    second_session_factory = db_module.get_session_factory()

    assert first_engine["url"] == "postgresql+psycopg://icloud:first-pass@db:5432/icloud_index"
    assert (
        second_engine["url"]
        == "postgresql+psycopg://icloud:next%2Fpass@db:5432/icloud_index_v2"
    )
    assert first_engine is not second_engine
    assert first_session_factory is not second_session_factory
    assert created_urls == [
        "postgresql+psycopg://icloud:first-pass@db:5432/icloud_index",
        "postgresql+psycopg://icloud:next%2Fpass@db:5432/icloud_index_v2",
    ]


def test_compose_service_validates_database_layer_before_starting_api():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    config = json.loads(result.stdout)
    service_command = " ".join(config["services"]["service"]["command"])

    assert "icloud_index_service.db" in service_command
    assert "uvicorn icloud_index_service.main:app" in service_command
