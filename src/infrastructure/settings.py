from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    banking_trusted_origins: list[str] = []
    registration_service_credential: SecretStr | None = None
    crp_customer_provisioning_credential: SecretStr | None = None
    crp_customer_service_url: str | None = None
    crp_customer_allow_insecure_http: bool = False
    crp_customer_request_timeout: float = Field(default=2.0, gt=0, le=10, allow_inf_nan=False)

    app_env: Literal["development", "test", "production"] = "production"
    auth_service_internal_url: str | None = None
    auth_service_credential: SecretStr | None = None
    auth_service_id: str = "cbs-backend"
    auth_application_code: Literal["CBS"] = "CBS"
    auth_session_cookie_name: str = "auth_session"
    auth_request_timeout: float = Field(default=2.0, gt=0, le=10, allow_inf_nan=False)
    auth_allow_insecure_http: bool = False
    auth_debug_endpoint_enabled: bool = False

    @field_validator("crp_customer_provisioning_credential", "registration_service_credential")
    @classmethod
    def valid_customer_provisioning_key(cls, value: SecretStr | None) -> SecretStr | None:
        import re

        if value is not None and re.fullmatch(r"[0-9a-f]{64}", value.get_secret_value()) is None:
            raise ValueError("Customer provisioning key must be 64 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> Self:
        if bool(self.auth_service_internal_url) != bool(self.auth_service_credential):
            raise ValueError("Auth service URL and credential must be configured together")
        if self.auth_debug_endpoint_enabled and self.app_env not in {"development", "test"}:
            raise ValueError("Auth diagnostics require an explicit development or test environment")
        if self.auth_debug_endpoint_enabled and not self.auth_service_internal_url:
            raise ValueError("Auth diagnostics require auth service configuration")
        return self

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
