import json
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from auth_client import ActorType, CurrentActor
from fastapi.testclient import TestClient

from api.authentication import get_current_actor
from api.dependencies import get_customer_identity
from api.main import create_app
from infrastructure.customer_service_client import CustomerServiceClient
from infrastructure.settings import Settings
from ports.customer_directory import CustomerDirectoryUnavailable
from ports.customer_identity import CustomerIdentityUnavailable
from ports.customer_onboarding import (
    CustomerProfileRejected,
    CustomerProvisioningUnavailable,
    OnboardingConflict,
)

KEY = "a" * 64


def client_for(handler):
    return CustomerServiceClient(
        "https://customers.test", KEY, transport=httpx.MockTransport(handler)
    )


def test_resolution_validates_contract_and_service_authentication():
    actor, customer, calls = uuid4(), uuid4(), []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + KEY
        assert request.headers["X-Service-ID"] == "cbs-backend"
        assert request.url.path == f"/internal/v1/actors/{actor}/customer"
        assert request.extensions["timeout"]["connect"] == 1
        return httpx.Response(
            200,
            json={
                "actor_id": str(actor),
                "customer_id": str(customer),
                "status": "LINKED",
            },
        )

    with client_for(handler) as client:
        assert client.resolve_customer_id(actor) == customer
    assert len(calls) == 1 and client.client.is_closed


@pytest.mark.parametrize(
    "status,body",
    [
        (200, {}),
        (200, []),
        (200, {"actor_id": str(uuid4()), "status": "PENDING_LINK"}),
        (200, {"actor_id": "same", "customer_id": "bad", "status": "LINKED"}),
        (301, {}),
        (401, {}),
        (403, {}),
        (404, {}),
        (500, {}),
        (503, {}),
    ],
)
def test_invalid_responses_never_grant_access(status, body):
    with client_for(lambda request: httpx.Response(status, json=body)) as client:
        with pytest.raises(CustomerIdentityUnavailable):
            client.resolve_customer_id(uuid4())


def test_pending_link_is_distinct_from_unavailable():
    actor = uuid4()
    with client_for(
        lambda request: httpx.Response(
            200,
            json={
                "actor_id": str(actor),
                "customer_id": None,
                "status": "PENDING_LINK",
            },
        )
    ) as client:
        assert client.resolve_customer_id(actor) is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="private-data"),
        httpx.Response(200, content=b"{" * 70000, headers={"Content-Type": "application/json"}),
        httpx.Response(200, content=b"broken", headers={"Content-Type": "application/json"}),
    ],
)
def test_malformed_and_oversized_response(response):
    with client_for(lambda request: response) as client:
        with pytest.raises(CustomerIdentityUnavailable):
            client.resolve_customer_id(uuid4())


def test_network_errors_fail_closed_and_are_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("private-service-credential")

    with client_for(handler) as client:
        with pytest.raises(CustomerIdentityUnavailable, match="Customer Service unavailable"):
            client.resolve_customer_id(uuid4())
        with pytest.raises(CustomerDirectoryUnavailable):
            client.exists(uuid4())
        with pytest.raises(CustomerProvisioningUnavailable):
            client.onboard(uuid4(), {}, "CZK")


def test_exists_checks_customer_service_and_does_not_fetch_profile():
    customer = uuid4()
    with client_for(
        lambda request: httpx.Response(200, json={"customer_id": str(customer)})
    ) as client:
        assert client.exists(customer)
    with client_for(lambda request: httpx.Response(404)) as client:
        assert not client.exists(customer)


@pytest.mark.parametrize(
    "status,error", [(409, OnboardingConflict), (422, CustomerProfileRejected)]
)
def test_onboarding_rejections(status, error):
    with client_for(lambda request: httpx.Response(status)) as client:
        with pytest.raises(error):
            client.onboard(uuid4(), {}, "CZK")


def test_onboarding_forwards_verified_actor_proof_and_validates_result():
    actor, customer = uuid4(), uuid4()

    def handler(request):
        body = json.loads(request.content)
        assert body == {"actor_id": str(actor), "currency": "CZK", "session_token": "proof"}
        return httpx.Response(
            200,
            json={
                "actor_id": str(actor),
                "customer_id": str(customer),
                "status": "LINKED",
            },
        )

    with client_for(handler) as client:
        assert client.onboard(actor, {}, "CZK", "proof") == customer


def test_me_uses_remote_identity_and_admin_does_not_require_customer_service():
    actor = CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER)
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_current_actor] = lambda: actor
    with TestClient(app) as client:
        assert client.get("/me").status_code == 503
        identities = Mock()
        identities.resolve_customer_id.return_value = None
        app.dependency_overrides[get_customer_identity] = lambda: identities
        assert client.get("/me").json()["link_status"] == "PENDING_LINK"
        identities.resolve_customer_id.return_value = uuid4()
        result = client.get("/me", params={"customer_id": str(uuid4())})
        assert result.json()["customer_id"] == str(identities.resolve_customer_id.return_value)
        app.dependency_overrides.pop(get_customer_identity)
        actor = CurrentActor(uuid4(), "CBS", ActorType.ADMIN)
        assert client.get("/me").json()["link_status"] == "NOT_APPLICABLE"
