from collections.abc import Iterator
from uuid import uuid4

import pytest
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, text

from infrastructure.persistence.database import create_database_engine
from infrastructure.persistence.migrate import initialize_database
from infrastructure.settings import Settings


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    test_database_url: SecretStr | None = None


@pytest.fixture
def test_settings() -> Settings:
    url = IntegrationSettings().test_database_url
    if url is None:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
    settings = Settings(database_mode="postgres", database_url=url, _env_file=None)
    if not (settings.postgresql_url().database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must use a dedicated database whose name ends in _test")
    return settings


@pytest.fixture
def isolated_database_settings(test_settings: Settings) -> Iterator[Settings]:
    # A search_path alone cannot isolate the explicitly qualified banking schema.
    database = f"cbs_{uuid4().hex}_test"
    admin = create_database_engine(test_settings)
    created = False
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        created = True
        url = test_settings.postgresql_url()
        yield Settings(
            database_mode="postgres",
            database_url=SecretStr(
                url.set(database=database, query={}).render_as_string(hide_password=False)
            ),
            _env_file=None,
        )
    finally:
        try:
            if created:
                with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                    connection.execute(text(f'DROP DATABASE "{database}"'))
        finally:
            admin.dispose()


@pytest.fixture
def migrated_engine(isolated_database_settings: Settings) -> Iterator[Engine]:
    engine = create_database_engine(isolated_database_settings)
    try:
        initialize_database(engine)
        yield engine
    finally:
        engine.dispose()
