from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.main import create_app
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.models import AccountORM, ActorCustomerLinkORM
from infrastructure.settings import Settings
from ports.customer_onboarding import CustomerProvisioningUnavailable

pytestmark = pytest.mark.integration
PROFILE = {
    "birth_date": "1990-01-01",
    "employment_status": "EMPLOYED",
    "employment_months": None,
    "monthly_net_income": "2000.00",
    "monthly_housing_cost": "500.00",
    "monthly_debt_payments": "0.00",
    "monthly_basic_expenses": "300.00",
    "housing_status": "RENT",
    "country_of_residence": "ES",
    "currency": "CZK",
}
KEY = "a" * 64
HEADERS = {"Authorization": "Bearer " + KEY, "X-Service-ID": "auth-registration"}


@pytest.fixture
def internal_registration(migrated_engine, isolated_database_settings):
    settings = Settings(
        database_mode="postgres",
        persistence_backend="postgres",
        database_url=isolated_database_settings.database_url,
        registration_service_credential=KEY,
        crp_customer_service_url="http://127.0.0.1:8098",
        crp_customer_allow_insecure_http=True,
        crp_customer_provisioning_credential="b" * 64,
        _env_file=None,
    )
    with patch(
        "infrastructure.crp_customer_provisioner.CRPCustomerProvisioner.ensure",
        side_effect=lambda customer_id, profile: customer_id,
    ) as provision:
        with TestClient(
            create_app(settings, internal=True), raise_server_exceptions=False
        ) as client:
            yield client, provision, settings


def test_internal_registration_requires_trusted_service_and_is_not_public(internal_registration):
    client, provision, settings = internal_registration
    path = f"/internal/registrations/{uuid4()}"
    assert client.put(path, json=PROFILE).status_code == 401
    assert (
        client.put(
            path, json=PROFILE, headers={**HEADERS, "Origin": "http://localhost"}
        ).status_code
        == 403
    )
    assert (
        client.put(
            path, json=PROFILE, headers={**HEADERS, "Sec-Fetch-Site": "same-origin"}
        ).status_code
        == 403
    )
    assert (
        client.put(path, json={**PROFILE, "actor_id": str(uuid4())}, headers=HEADERS).status_code
        == 422
    )
    assert client.get("/docs").status_code == 404
    assert client.get("/me").status_code == 404
    with TestClient(create_app(settings)) as public:
        assert public.put(path, json=PROFILE, headers=HEADERS).status_code == 404
    provision.assert_not_called()


def test_internal_registration_creates_one_link_and_account_and_confirms(
    internal_registration, migrated_engine
):
    client, provision, _ = internal_registration
    actor_id = uuid4()
    path = f"/internal/registrations/{actor_id}"
    assert client.get(path, headers=HEADERS).status_code == 409
    first = client.put(path, json=PROFILE, headers=HEADERS)
    assert first.status_code == 200
    again = client.put(path, json=PROFILE, headers=HEADERS)
    assert again.json() == first.json()
    provision.assert_called_once()
    assert client.get(path, headers=HEADERS).json() == {
        "actor_id": str(actor_id),
        "customer_id": first.json()["customer_id"],
        "status": "LINKED",
    }
    with create_session_factory(migrated_engine)() as db:
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 1
        assert (
            str(db.get(ActorCustomerLinkORM, actor_id).customer_id) == first.json()["customer_id"]
        )


def test_uncertain_customer_response_reuses_same_identity(internal_registration, migrated_engine):
    client, provision, _ = internal_registration
    path = f"/internal/registrations/{uuid4()}"
    provision.side_effect = CustomerProvisioningUnavailable()
    assert client.put(path, json=PROFILE, headers=HEADERS).status_code == 503
    customer_id = provision.call_args.args[0]
    assert client.get(path, headers=HEADERS).status_code == 409
    provision.side_effect = lambda customer_id, profile: customer_id
    assert client.put(path, json=PROFILE, headers=HEADERS).status_code == 200
    assert provision.call_args.args[0] == customer_id
