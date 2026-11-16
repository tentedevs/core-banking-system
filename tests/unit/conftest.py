from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "BANKING_TRUSTED_ORIGINS",
        "CRP_CUSTOMER_SERVICE_URL",
        "CRP_CUSTOMER_PROVISIONING_CREDENTIAL",
        "CRP_CUSTOMER_ALLOW_INSECURE_HTTP",
        "CRP_CUSTOMER_REQUEST_TIMEOUT",
        "DATABASE_MODE",
        "PERSISTENCE_BACKEND",
        "DATABASE_URL",
        "APP_ENV",
        "AUTH_SERVICE_INTERNAL_URL",
        "AUTH_SERVICE_CREDENTIAL",
        "AUTH_SERVICE_ID",
        "AUTH_APPLICATION_CODE",
        "AUTH_SESSION_COOKIE_NAME",
        "AUTH_REQUEST_TIMEOUT",
        "AUTH_ALLOW_INSECURE_HTTP",
        "AUTH_DEBUG_ENDPOINT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
