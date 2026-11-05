from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from auth_client import ActorType, CurrentActor
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.authentication import get_current_actor
from api.main import create_app
from api.routers.customer_onboarding import OnboardingRequest
from application.use_cases.onboard_customer import OnboardCustomer
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.models import AccountBalanceORM, AccountORM, ActorCustomerLinkORM
from infrastructure.settings import Settings
from ports.customer_onboarding import (
    CustomerProfileRejected,
    CustomerProvisioningUnavailable,
    OnboardingConflict,
)

pytestmark = pytest.mark.integration
PROFILE = {
    "birth_date": "1990-01-01",
    "employment_status": "EMPLOYED",
    "employment_months": 24,
    "monthly_net_income": "2000.00",
    "monthly_housing_cost": "500.00",
    "monthly_debt_payments": "0.00",
    "monthly_basic_expenses": "300.00",
    "housing_status": "RENT",
    "country_of_residence": "ES",
    "currency": "CZK",
}


@pytest.fixture
def setup(migrated_engine):
    sessions = create_session_factory(migrated_engine)

    def work():
        return SQLAlchemyAccountUnitOfWork(sessions)

    actor = CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER)
    records = {}
    customers = Mock()

    def ensure(customer_id, profile):
        records.setdefault(customer_id, profile)
        assert records[customer_id] == profile
        return customer_id

    customers.ensure.side_effect = ensure
    yield work, sessions, actor, customers, records


def test_onboarding_creates_one_link_account_and_zero_balance(setup):
    work, sessions, actor, customers, records = setup
    profile = OnboardingRequest(**PROFILE).customer_profile()
    first = OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    again = OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    assert first.id == again.id and len(records) == 1
    customers.ensure.assert_called_once()
    with sessions() as db:
        assert db.get(ActorCustomerLinkORM, actor.actor_id).customer_id == first.customer_id
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 1
        assert db.get(AccountBalanceORM, first.id).booked_balance == 0
    with pytest.raises(OnboardingConflict):
        OnboardCustomer(work(), customers).execute(
            actor, {**profile, "country_of_residence": "CZ"}, "CZK"
        )


def test_network_failure_reuses_durable_customer_identity(setup):
    work, sessions, actor, customers, records = setup
    profile = OnboardingRequest(**PROFILE).customer_profile()
    original = customers.ensure.side_effect

    def uncertain(customer_id, body):
        original(customer_id, body)
        raise CustomerProvisioningUnavailable("uncertain")

    customers.ensure.side_effect = uncertain
    with pytest.raises(CustomerProvisioningUnavailable):
        OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 0
        assert db.scalar(select(func.count()).select_from(ActorCustomerLinkORM)) == 0
    customers.ensure.side_effect = original
    account = OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    assert len(records) == 1 and account.customer_id in records


def test_local_failure_rolls_back_link_and_account_but_retry_recovers_same_crp_customer(setup):
    work, sessions, actor, customers, records = setup
    profile = OnboardingRequest(**PROFILE).customer_profile()
    with patch(
        "application.use_cases.onboard_customer.CreateAccount.create_in_transaction",
        side_effect=RuntimeError("local failure"),
    ):
        with pytest.raises(RuntimeError):
            OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 0
        assert db.scalar(select(func.count()).select_from(ActorCustomerLinkORM)) == 0
    result = OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    assert len(records) == 1 and result.customer_id in records


def test_concurrent_onboarding_creates_one_account(setup):
    work, sessions, actor, customers, records = setup
    profile = OnboardingRequest(**PROFILE).customer_profile()

    def execute():
        return OnboardCustomer(work(), customers).execute(actor, profile, "CZK")

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(execute), pool.submit(execute)
        assert a.result(timeout=15).id == b.result(timeout=15).id
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 1
    assert len(records) == 1


def test_rejected_profile_can_be_corrected_without_account_creation(setup):
    work, sessions, actor, customers, _ = setup
    profile = OnboardingRequest(**PROFILE).customer_profile()
    original = customers.ensure.side_effect
    customers.ensure.side_effect = CustomerProfileRejected("invalid")
    with pytest.raises(CustomerProfileRejected):
        OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    customers.ensure.side_effect = original
    result = OnboardCustomer(work(), customers).execute(
        actor, {**profile, "country_of_residence": "CZ"}, "CZK"
    )
    assert result.customer_id


def test_api_uses_authenticated_actor_not_supplied_ids(migrated_engine, isolated_database_settings):
    actor = CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER)
    settings = Settings(
        persistence_backend="postgres",
        database_url=isolated_database_settings.database_url,
        crp_customer_service_url="https://crp.test",
        crp_customer_provisioning_credential="b" * 64,
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_current_actor] = lambda: actor
    customers = Mock()
    customers.__enter__ = Mock(return_value=customers)
    customers.__exit__ = Mock(return_value=False)
    customers.ensure.side_effect = lambda customer_id, profile: customer_id
    with (
        patch("api.routers.customer_onboarding.CRPCustomerProvisioner", return_value=customers),
        TestClient(app) as client,
    ):
        assert (
            client.post("/me/onboarding", json={**PROFILE, "actor_id": str(uuid4())}).status_code
            == 422
        )
        result = client.post("/me/onboarding", json=PROFILE)
        assert result.status_code == 201
        identity = client.get("/me").json()
        assert identity["actor_id"] == str(actor.actor_id)
        assert (
            identity["customer_id"] == result.json()["customer_id"]
            and identity["link_status"] == "LINKED"
        )
        assert client.get("/me/accounts").json()["pagination"]["total_items"] == 1
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            uuid4(), "CBS", ActorType.ADMIN
        )
        assert client.post("/me/onboarding", json=PROFILE).status_code == 403
        app.dependency_overrides.pop(get_current_actor)
        assert client.post("/me/onboarding", json=PROFILE).status_code == 401


def test_real_crp_creation_and_cbs_account_relationship(setup):
    import os

    import httpx

    from infrastructure.crp_customer_provisioner import CRPCustomerProvisioner

    url = os.environ.get("CRP_ONBOARDING_TEST_URL")
    key = os.environ.get("CRP_ONBOARDING_TEST_CREDENTIAL")
    if not url or not key:
        pytest.skip("Set CRP_ONBOARDING_TEST_* for the real service integration")
    work, sessions, actor, _, _ = setup
    profile = OnboardingRequest(**PROFILE).customer_profile()
    with CRPCustomerProvisioner(url, key, allow_insecure_http=True) as customers:
        result = OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
        again = OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    assert again.id == result.id
    response = httpx.get(f"{url}/customers/{result.customer_id}", trust_env=False)
    assert response.status_code == 200 and response.json()["id"] == str(result.customer_id)
    with sessions() as db:
        assert db.get(ActorCustomerLinkORM, actor.actor_id).customer_id == result.customer_id
        assert db.get(AccountORM, result.id).customer_id == result.customer_id
        assert db.get(AccountBalanceORM, result.id).booked_balance == 0


def test_completed_onboarding_cannot_bypass_operator_unlink(setup):
    from infrastructure.persistence.repositories.actor_customer_link_repository import (
        SQLAlchemyActorCustomerLinkRepository,
    )

    work, sessions, actor, customers, _ = setup
    profile = OnboardingRequest(**PROFILE).customer_profile()
    OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    with sessions() as db, db.begin():
        SQLAlchemyActorCustomerLinkRepository(db).remove_link(actor.actor_id)
    with pytest.raises(OnboardingConflict):
        OnboardCustomer(work(), customers).execute(actor, profile, "CZK")
    with sessions() as db:
        assert db.get(ActorCustomerLinkORM, actor.actor_id) is None
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 1
