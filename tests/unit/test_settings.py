from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from infrastructure.settings import Settings

TEST_URL = "postgresql+psycopg://test_user@localhost:5433/core_banking_test"


def test_memory_mode_does_not_require_database_url() -> None:
    settings = Settings()
    assert settings.database_mode == "memory"
    assert settings.database_url is None


@pytest.mark.parametrize("value", [None, "", "   "])
def test_postgres_mode_requires_database_url(value: str | None) -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL is required"):
        Settings(database_mode="postgres", database_url=value)


def test_read_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_MODE", "postgres")
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    settings = Settings()
    assert settings.database_mode == "postgres"
    assert settings.postgresql_url().drivername == "postgresql+psycopg"
    assert settings.postgresql_url().database == "core_banking_test"


def test_read_dotenv_and_environment_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(f"DATABASE_MODE=postgres\nDATABASE_URL={TEST_URL}\n")
    assert Settings().postgresql_url().host == "localhost"

    monkeypatch.setenv("DATABASE_URL", TEST_URL.replace("localhost", "other-host"))
    assert Settings().postgresql_url().host == "other-host"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://test_user@localhost/core_banking_test",
        "postgresql+psycopg2://test_user@localhost/core_banking_test",
        "postgresql+asyncpg://test_user@localhost/core_banking_test",
        "sqlite:///example.db",
        "not-a-url",
        "postgresql+psycopg://test_user@localhost:invalid/core_banking_test",
        "postgresql+psycopg://test_user@localhost",
    ],
)
def test_invalid_database_url(url: str) -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(database_mode="postgres", database_url=url)


def test_url_can_omit_password() -> None:
    settings = Settings(database_mode="postgres", database_url=SecretStr(TEST_URL))
    assert settings.postgresql_url().password is None


def test_configuration_representation_hides_password() -> None:
    password = "fake-password-for-redaction-test"
    url = f"postgresql+psycopg://test_user:{password}@localhost/core_banking_test"
    settings = Settings(database_mode="postgres", database_url=url)
    assert password not in repr(settings)
    assert password not in str(settings.postgresql_url())


def test_invalid_url_error_does_not_expose_password() -> None:
    password = "fake-password-for-redaction-test"
    with pytest.raises(ValidationError) as error:
        Settings(database_mode="postgres", database_url=f"postgresql://user:{password}@host/db")
    assert password not in str(error.value)


def test_explicit_database_access_requires_url_even_in_memory_mode() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Settings().postgresql_url()


def test_postgres_persistence_requires_database_url() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL is required"):
        Settings(persistence_backend="postgres", database_url=None, _env_file=None)
