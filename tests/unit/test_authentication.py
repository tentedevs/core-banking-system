from collections.abc import Iterator
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from auth_client import AuthServiceClient, AuthServiceUnavailable
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import create_app
from infrastructure.settings import Settings

KEY = "b" * 64
TOKEN = "unit-session-token"
ACTOR_ID = str(uuid4())


def auth_settings(**updates: object) -> Settings:
    values = dict(
        app_env="test",
        auth_service_internal_url="http://auth.test",
        auth_service_credential=KEY,
        auth_allow_insecure_http=True,
        auth_debug_endpoint_enabled=True,
    )
    values.update(updates)
    return Settings(**values)


@pytest.fixture
def resolver() -> Iterator[tuple[TestClient, list[httpx.Request], dict[str, object]]]:
    calls: list[httpx.Request] = []
    state: dict[str, object] = {
        "status": 200,
        "body": {
            "actor_id": ACTOR_ID,
            "application_code": "CBS",
            "actor_type": "CUSTOMER",
            "is_active": True,
        },
    }

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "error" in state:
            raise state["error"]
        return httpx.Response(state["status"], json=state["body"])

    shared = AuthServiceClient(
        base_url="http://auth.test",
        service_id="cbs-backend",
        service_credential=KEY,
        application_code="CBS",
        allow_insecure_http=True,
        transport=httpx.MockTransport(handle),
    )
    with patch("api.main.AuthServiceClient", return_value=shared):
        with TestClient(create_app(auth_settings())) as browser:
            browser.cookies.set("auth_session", TOKEN)
            yield browser, calls, state
    with pytest.raises(AuthServiceUnavailable):
        shared.resolve(TOKEN)


@pytest.mark.parametrize("role", ["ADMIN", "CUSTOMER"])
def test_verified_roles_and_private_request(resolver, role, caplog):
    browser, calls, state = resolver
    state["body"]["actor_type"] = role
    response = browser.get(
        "/dev/auth/whoami", params={"actor_type": "ADMIN", "actor_id": str(uuid4())}
    )
    assert response.status_code == 200
    assert response.json() == {"actor_id": ACTOR_ID, "application_code": "CBS", "actor_type": role}
    assert response.headers["cache-control"] == "no-store"
    assert calls[0].url.path == "/internal/auth/resolve"
    assert calls[0].headers["authorization"] == f"Bearer {KEY}"
    assert calls[0].headers["x-service-id"] == "cbs-backend"
    assert b'"application_code":"CBS"' in calls[0].content
    assert TOKEN not in response.text + caplog.text and KEY not in response.text + caplog.text


def test_missing_and_ambiguous_cookies(resolver):
    browser, calls, _ = resolver
    browser.cookies.clear()
    assert browser.get("/dev/auth/whoami").status_code == 401
    assert (
        browser.get(
            "/dev/auth/whoami", headers={"Cookie": "auth_session=a; auth_session=b"}
        ).status_code
        == 401
    )
    assert not calls


@pytest.mark.parametrize("reason", ["unknown", "expired", "revoked", "invalid-service-credential"])
def test_unauthorized_resolution(resolver, reason):
    browser, _, state = resolver
    state.update(status=401, body={"detail": reason})
    response = browser.get("/dev/auth/whoami")
    assert response.status_code == 401 and reason not in response.text
    assert browser.get("/me").status_code == 401


def test_no_application_access(resolver):
    browser, _, state = resolver
    state["status"] = 403
    assert browser.get("/dev/auth/whoami").status_code == 403
    assert browser.get("/me").status_code == 403


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("private-token"), httpx.ConnectError("private-key")]
)
def test_network_failure_closed(resolver, error, caplog):
    browser, _, state = resolver
    state["error"] = error
    response = browser.get("/dev/auth/whoami")
    assert response.status_code == 503
    assert "private-" not in response.text + caplog.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"actor_id": "bad"},
        {"actor_id": ACTOR_ID, "application_code": "CRP", "actor_type": "ADMIN", "is_active": True},
        {
            "actor_id": ACTOR_ID,
            "application_code": "CBS",
            "actor_type": "ADMIN",
            "is_active": False,
        },
        {"actor_id": ACTOR_ID, "application_code": "CBS", "actor_type": "ROOT", "is_active": True},
    ],
)
def test_malformed_responses_fail_closed(resolver, body):
    browser, _, state = resolver
    state["body"] = body
    assert browser.get("/dev/auth/whoami").status_code == 503


def test_diagnostic_is_opt_in_and_banking_requires_authentication():
    with TestClient(create_app(Settings())) as browser:
        assert browser.get("/dev/auth/whoami").status_code == 404
        assert browser.get("/health").status_code == 200
        assert browser.get("/accounts").status_code == 401
    with pytest.raises(ValidationError):
        auth_settings(app_env="production")


@pytest.mark.parametrize(
    "updates",
    [
        {"auth_request_timeout": 0},
        {"auth_request_timeout": float("inf")},
        {"auth_application_code": "CRP"},
        {"auth_service_credential": None},
    ],
)
def test_invalid_settings(updates):
    with pytest.raises(ValidationError):
        auth_settings(**updates)


@pytest.mark.parametrize("status", [400, 404, 429, 500, 502, 503])
def test_unexpected_upstream_errors_fail_closed(resolver, status):
    browser, _, state = resolver
    state.update(status=status, body={"detail": "upstream-private-data"})
    response = browser.get("/dev/auth/whoami")
    assert response.status_code == 503
    assert "upstream-private-data" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/me/accounts",
        f"/me/accounts/{ACTOR_ID}",
        f"/me/accounts/{ACTOR_ID}/balance",
        f"/me/accounts/{ACTOR_ID}/movements",
        "/me/transactions",
        f"/me/transactions/{ACTOR_ID}",
    ],
)
def test_customer_read_endpoints_fail_closed_before_data_access(resolver, path):
    browser, calls, state = resolver
    state["error"] = httpx.ReadTimeout("private-session")
    with patch("api.routers.customer_reads.SQLAlchemyActorCustomerLinkRepository") as links:
        response = browser.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Authentication service unavailable"}
        links.assert_not_called()
    assert len(calls) == 1
    browser.cookies.clear()
    assert browser.get(path).status_code == 401
    assert len(calls) == 1
