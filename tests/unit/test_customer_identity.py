from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
import pytest
from auth_client import ActorType, CurrentActor
from fastapi.testclient import TestClient

from api.authentication import get_current_actor
from api.dependencies import get_session
from api.main import create_app
from application.customer_identity import LinkActorToCustomer, ResolveCustomerIdentity
from domain.customer_identity.entities import ActorCustomerLink
from infrastructure.crp_customer_directory import CRPCustomerDirectory
from infrastructure.settings import Settings
from ports.customer_directory import CustomerDirectoryUnavailable, CustomerNotFound


@pytest.mark.parametrize("linked", [False, True])
def test_customer_me_uses_persisted_mapping(linked):
    actor = CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER)
    customer = uuid4()
    link = ActorCustomerLink(actor.actor_id, customer, datetime.now(UTC)) if linked else None
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_current_actor] = lambda: actor
    app.dependency_overrides[get_session] = lambda: Mock()
    with patch("api.routers.me.SQLAlchemyActorCustomerLinkRepository") as repo:
        repo.return_value.get_by_actor_id.return_value = link
        with TestClient(app) as client:
            response = client.get("/me", params={"customer_id": str(uuid4())})
        repo.return_value.get_by_actor_id.assert_called_once_with(actor.actor_id)
    assert response.status_code == 200
    assert response.json() == {
        "actor_id": str(actor.actor_id),
        "application_code": "CBS",
        "actor_type": "CUSTOMER",
        "customer_id": str(customer) if linked else None,
        "link_status": "LINKED" if linked else "PENDING_LINK",
    }
    assert response.headers["cache-control"] == "no-store"


def test_admin_me_does_not_invent_mapping():
    actor = CurrentActor(uuid4(), "CBS", ActorType.ADMIN)
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_current_actor] = lambda: actor
    with TestClient(app) as client:
        result = client.get("/me")
    assert result.status_code == 200
    assert result.json()["customer_id"] is None
    assert result.json()["link_status"] == "NOT_APPLICABLE"


def test_missing_authentication_and_no_self_service_links():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/me").status_code == 401
        assert client.post("/me/link", json={"customer_id": str(uuid4())}).status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/accounts"),
        ("POST", "/accounts"),
        ("GET", "/transactions"),
        ("POST", "/transactions/deposits"),
        ("POST", "/transactions/withdrawals"),
        ("POST", "/transactions/transfers"),
        ("GET", f"/accounts/{uuid4()}/balance"),
        ("GET", f"/accounts/{uuid4()}/movements"),
    ],
)
def test_customers_cannot_use_administration_routes(method, path):
    app = create_app(Settings(_env_file=None))
    actor = CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER)
    app.dependency_overrides[get_current_actor] = lambda: actor
    with TestClient(app) as client:
        assert client.request(method, path).status_code == 403


def test_admin_write_requires_trusted_browser_origin():
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), "CBS", ActorType.ADMIN
    )
    with TestClient(app) as client:
        assert client.post("/accounts", headers={"Origin": "https://evil.test"}).status_code == 403
        assert (
            client.post("/accounts", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 403
        )


def test_linking_nonexistent_customer_does_not_write():
    repo, directory = Mock(), Mock()
    directory.exists.return_value = False
    with pytest.raises(CustomerNotFound):
        LinkActorToCustomer(repo, directory).execute(uuid4(), uuid4())
    repo.create_link.assert_not_called()


def test_lookup_and_linking_use_explicit_identifiers():
    repo, directory = Mock(), Mock()
    actor, customer = uuid4(), uuid4()
    repo.get_by_actor_id.return_value = ActorCustomerLink(actor, customer, datetime.now(UTC))
    assert ResolveCustomerIdentity(repo).resolve_customer_id(actor) == customer
    directory.exists.return_value = True
    LinkActorToCustomer(repo, directory).execute(actor, customer)
    repo.create_link.assert_called_once_with(actor, customer)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, "match", True),
        (404, {}, False),
        (200, {}, None),
        (503, {}, None),
        (200, {"id": str(uuid4())}, None),
    ],
)
def test_crp_customer_contract(status, body, expected):
    customer = uuid4()
    if body == "match":
        body = {"id": str(customer), "unneeded_crp_fields": "not persisted"}
    with CRPCustomerDirectory(
        "http://crp.test",
        allow_insecure_http=True,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)),
    ) as directory:
        if expected is None:
            with pytest.raises(CustomerDirectoryUnavailable):
                directory.exists(customer)
        else:
            assert directory.exists(customer) is expected


def test_crp_network_failure_is_not_customer_not_found():
    def fail(request):
        raise httpx.ReadTimeout("sensitive")

    with CRPCustomerDirectory(
        "http://crp.test", allow_insecure_http=True, transport=httpx.MockTransport(fail)
    ) as directory:
        with pytest.raises(CustomerDirectoryUnavailable, match="Customer directory unavailable"):
            directory.exists(uuid4())
