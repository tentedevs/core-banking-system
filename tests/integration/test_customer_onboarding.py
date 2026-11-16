from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest
from auth_client import ActorType, CurrentActor
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.authentication import get_current_actor
from api.dependencies import get_customer_identity, get_customer_service_client
from api.main import create_app
from application.use_cases.onboard_customer import OnboardCustomer
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.models import (
    AccountBalanceORM,
    AccountORM,
    ActorCustomerLinkORM,
    CustomerAccountOpeningORM,
    CustomerOnboardingORM,
)
from infrastructure.settings import Settings
from ports.customer_onboarding import CustomerProvisioningUnavailable
from tests.customer_service_fake import CustomerServiceFake

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
    actor = CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER)
    remote = CustomerServiceFake()
    yield sessions, actor, remote
    remote.client.close()


def execute(setup):
    sessions, actor, remote = setup
    profile = {key: value for key, value in PROFILE.items() if key != "currency"}
    return OnboardCustomer(SQLAlchemyAccountUnitOfWork(sessions), remote.client).execute(
        actor,
        profile,
        "CZK",
        "verified-session",
    )


def test_first_and_repeated_onboarding_create_only_banking_records(setup):
    sessions, actor, remote = setup
    first, second = execute(setup), execute(setup)
    assert first.id == second.id
    assert first.customer_id == remote.records[actor.actor_id][0]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 1
        assert db.get(AccountBalanceORM, first.id).booked_balance == 0
        assert db.scalar(select(func.count()).select_from(CustomerAccountOpeningORM)) == 1
        assert db.scalar(select(func.count()).select_from(ActorCustomerLinkORM)) == 0
        assert db.scalar(select(func.count()).select_from(CustomerOnboardingORM)) == 0


def test_uncertain_remote_commit_and_retry(setup):
    sessions, actor, remote = setup
    remote.lose_response = True
    with pytest.raises(CustomerProvisioningUnavailable):
        execute(setup)
    customer = remote.records[actor.actor_id][0]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 0
    remote.lose_response = False
    assert execute(setup).customer_id == customer


def test_local_failure_after_remote_success_recovers_without_remote_rollback(setup):
    sessions, actor, remote = setup
    with patch(
        "application.use_cases.onboard_customer.CreateAccount.create_in_transaction",
        side_effect=RuntimeError("local failure"),
    ):
        with pytest.raises(RuntimeError):
            execute(setup)
    assert actor.actor_id in remote.records
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AccountORM)) == 0
    assert execute(setup).customer_id == remote.records[actor.actor_id][0]


def test_concurrent_account_opening_is_idempotent(setup):
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(execute, setup), pool.submit(execute, setup)
        assert a.result(timeout=15).id == b.result(timeout=15).id


def test_browser_cannot_supply_identity_or_customer(setup, isolated_database_settings):
    _, actor, remote = setup
    app = create_app(
        Settings(
            persistence_backend="postgres",
            database_url=isolated_database_settings.database_url,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_current_actor] = lambda: actor
    app.dependency_overrides[get_customer_service_client] = lambda: remote.client
    app.dependency_overrides[get_customer_identity] = lambda: remote.client
    with TestClient(app) as client:
        client.cookies.set("auth_session", "verified-session")
        for field in ("actor_id", "customer_id"):
            assert (
                client.post("/me/onboarding", json={**PROFILE, field: str(uuid4())}).status_code
                == 422
            )
        result = client.post("/me/onboarding", json=PROFILE)
        assert result.status_code == 201
        assert client.get("/me").json()["customer_id"] == result.json()["customer_id"]
        assert client.get("/me/accounts").json()["pagination"]["total_items"] == 1
        remote.unavailable = True
        assert client.get("/me").status_code == 503
        assert client.get("/me/accounts").status_code == 503
        assert client.post("/me/onboarding", json=PROFILE).status_code == 503
