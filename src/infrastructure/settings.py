from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_mode: Literal["memory", "postgres"] = "memory"
    persistence_backend: Literal["memory", "postgres"] = "memory"
    database_url: SecretStr | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_url_is_missing(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_database_configuration(self) -> Self:
        if self.database_url is None:
            if self.persistence_backend == "postgres":
                raise ValueError("DATABASE_URL is required when PERSISTENCE_BACKEND=postgres")
            if self.database_mode == "postgres":
                raise ValueError("DATABASE_URL is required when DATABASE_MODE=postgres")
            return self
        try:
            url = make_url(self.database_url.get_secret_value())
        except (ArgumentError, ValueError) as exc:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy PostgreSQL URL") from exc
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use the postgresql+psycopg driver")
        if not url.database:
            raise ValueError("DATABASE_URL must specify a database name")
        return self

    def postgresql_url(self) -> URL:
        if self.database_url is None:
            raise ValueError("DATABASE_URL is required to connect to PostgreSQL")
        return make_url(self.database_url.get_secret_value())
