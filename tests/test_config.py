from icloud_index_service.config import Settings


def test_settings_build_database_url():
    settings = Settings(
        postgres_user="icloud",
        postgres_password="secret",
        postgres_host="db",
        postgres_port=5432,
        postgres_db="icloud_index",
    )

    assert settings.database_url == "postgresql+psycopg://icloud:secret@db:5432/icloud_index"
