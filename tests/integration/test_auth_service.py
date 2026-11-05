"""Opt-in real HTTP test; supply a session from an isolated auth test deployment."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from infrastructure.settings import Settings

pytestmark = pytest.mark.integration


def test_real_auth_service_resolves_cbs_customer() -> None:
    url = os.environ.get("CBS_AUTH_TEST_URL")
    if not url:
        pytest.skip("Set CBS_AUTH_TEST_* for an isolated running auth service")
    required = ("CBS_AUTH_TEST_CREDENTIAL", "CBS_AUTH_TEST_TOKEN", "CBS_AUTH_TEST_ACTOR_ID")
    if any(not os.environ.get(name) for name in required):
        pytest.fail("Incomplete CBS_AUTH_TEST_* integration configuration")
    settings = Settings(
        _env_file=None,
        app_env="test",
        persistence_backend="memory",
        database_mode="memory",
        auth_service_internal_url=url,
        auth_service_credential=os.environ["CBS_AUTH_TEST_CREDENTIAL"],
        auth_service_id="cbs-backend",
        auth_allow_insecure_http=True,
        auth_debug_endpoint_enabled=True,
    )
    with TestClient(create_app(settings)) as browser:
        browser.cookies.set("auth_session", os.environ["CBS_AUTH_TEST_TOKEN"])
        response = browser.get("/dev/auth/whoami")
        assert response.status_code == 200
        assert response.json() == {
            "actor_id": os.environ["CBS_AUTH_TEST_ACTOR_ID"],
            "application_code": "CBS",
            "actor_type": "CUSTOMER",
        }
        assert os.environ["CBS_AUTH_TEST_TOKEN"] not in response.text
        assert os.environ["CBS_AUTH_TEST_CREDENTIAL"] not in response.text
        browser.cookies.set("auth_session", uuid4().hex)
        assert browser.get("/dev/auth/whoami").status_code == 401
        browser.cookies.clear()
        assert browser.get("/dev/auth/whoami").status_code == 401
