from decimal import Decimal
from uuid import uuid4

import pytest
from auth_client import ActorType, CurrentActor
from fastapi.testclient import TestClient

from api.authentication import get_current_actor
from api.main import create_app
from application.account_messages import CreateAccountCommand
from application.transaction_messages import CreateDepositCommand, CreateTransferCommand
from application.use_cases.create_account import CreateAccount
from application.use_cases.create_deposit import CreateDeposit
from application.use_cases.create_transfer import CreateTransfer
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.repositories.actor_customer_link_repository import (
    SQLAlchemyActorCustomerLinkRepository,
)
from infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def customer_banking(migrated_engine, isolated_database_settings):
    sessions = create_session_factory(migrated_engine)

    def work():
        return SQLAlchemyAccountUnitOfWork(sessions)

    actor_a, actor_b, pending = uuid4(), uuid4(), uuid4()
    customer_a, customer_b = uuid4(), uuid4()
    a1 = CreateAccount(work()).execute(CreateAccountCommand(customer_a))
    a2 = CreateAccount(work()).execute(CreateAccountCommand(customer_a))
    b = CreateAccount(work()).execute(CreateAccountCommand(customer_b))
    with sessions() as session, session.begin():
        repo = SQLAlchemyActorCustomerLinkRepository(session)
        repo.create_link(actor_a, customer_a)
        repo.create_link(actor_b, customer_b)
    deposit_a = CreateDeposit(work()).execute(
        CreateDepositCommand(a1.id, Decimal("100"), "CZK", "secret-deposit-a")
    )
    deposit_b = CreateDeposit(work()).execute(
        CreateDepositCommand(b.id, Decimal("200"), "CZK", "secret-deposit-b")
    )
    cross = CreateTransfer(work()).execute(
        CreateTransferCommand(a1.id, b.id, Decimal("10"), "CZK", "secret-cross")
    )
    own = CreateTransfer(work()).execute(
        CreateTransferCommand(a1.id, a2.id, Decimal("5"), "CZK", "secret-own")
    )
    app = create_app(
        Settings(
            persistence_backend="postgres",
            database_url=isolated_database_settings.database_url,
            _env_file=None,
        )
    )
    state = {"actor": CurrentActor(actor_a, "CBS", ActorType.CUSTOMER)}
    app.dependency_overrides[get_current_actor] = lambda: state["actor"]
    with TestClient(app) as client:
        yield (
            client,
            state,
            (a1, a2, b),
            (deposit_a, deposit_b, cross, own),
            (actor_a, actor_b, pending),
            (customer_a, customer_b),
            app,
        )


def test_account_ownership_and_scoped_pagination(customer_banking):
    client, _, (a1, a2, b), _, _, (_, customer_b), _ = customer_banking
    result = client.get("/me/accounts", params={"limit": 1, "customer_id": str(customer_b)})
    assert result.status_code == 200
    data = result.json()
    assert data["pagination"]["total_items"] == 2
    second = client.get("/me/accounts", params={"limit": 1, "offset": 1}).json()
    assert {data["items"][0]["id"], second["items"][0]["id"]} == {str(a1.id), str(a2.id)}
    assert client.get("/me/accounts", params={"offset": 2}).json()["items"] == []
    assert client.get(f"/me/accounts/{a1.id}").json()["id"] == str(a1.id)
    assert client.get(f"/me/accounts/{a1.id}/balance").json()["booked_balance"] == "85.00"
    rows = client.get(f"/me/accounts/{a1.id}/movements", params={"limit": 1}).json()
    assert rows["pagination"]["total_items"] == 3
    assert rows["items"][0]["account_id"] == str(a1.id)
    assert "counterparty_account" not in rows["items"][0]
    for suffix in ("", "/balance", "/movements"):
        forbidden = client.get(f"/me/accounts/{b.id}{suffix}")
        missing = client.get(f"/me/accounts/{uuid4()}{suffix}")
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json()


def test_transactions_filter_before_pagination_without_duplicates(customer_banking):
    client, _, _, (deposit_a, deposit_b, cross, own), _, _, _ = customer_banking
    results = [
        client.get("/me/transactions", params={"limit": 1, "offset": index}).json()
        for index in range(3)
    ]
    assert all(row["pagination"]["total_items"] == 3 for row in results)
    assert {row["items"][0]["id"] for row in results} == {
        str(deposit_a.id),
        str(cross.id),
        str(own.id),
    }
    assert client.get("/me/transactions", params={"offset": 3}).json()["items"] == []
    assert (
        client.get("/me/transactions", params={"transaction_type": "TRANSFER"}).json()[
            "pagination"
        ]["total_items"]
        == 2
    )
    assert client.get("/me/transactions", params={"status": "REJECTED"}).json()["items"] == []
    response = client.get(f"/me/transactions/{deposit_b.id}")
    missing = client.get(f"/me/transactions/{uuid4()}")
    assert response.status_code == missing.status_code == 404
    assert response.json() == missing.json()


def test_cross_customer_transfer_redacts_other_movements_and_internal_fields(customer_banking):
    client, state, (a1, _, b), (_, _, cross, own), (_, actor_b, _), _, _ = customer_banking
    response = client.get(f"/me/transactions/{cross.id}")
    assert response.status_code == 200
    body = response.json()
    assert (
        "idempotency_key" not in body and "reversal_of_id" not in body and "created_at" not in body
    )
    assert str(b.id) not in response.text and "210.00" not in response.text
    assert body["movements"]["pagination"]["total_items"] == 1
    assert body["movements"]["items"][0]["account_id"] == str(a1.id)
    assert body["movements"]["items"][0]["direction"] == "DEBIT"
    assert (
        client.get(f"/me/transactions/{own.id}", params={"limit": 1}).json()["movements"][
            "pagination"
        ]["total_items"]
        == 2
    )
    state["actor"] = CurrentActor(actor_b, "CBS", ActorType.CUSTOMER)
    other = client.get(f"/me/transactions/{cross.id}").json()
    assert other["movements"]["items"][0]["account_id"] == str(b.id)
    assert other["movements"]["items"][0]["direction"] == "CREDIT"
    assert other["movements"]["pagination"]["total_items"] == 1


def test_pending_admin_missing_auth_and_link_removal(customer_banking):
    client, state, (a1, _, _), (deposit, _, _, _), (actor_a, _, pending), _, app = customer_banking
    paths = [
        "/me/accounts",
        f"/me/accounts/{a1.id}",
        f"/me/accounts/{a1.id}/balance",
        f"/me/accounts/{a1.id}/movements",
        "/me/transactions",
        f"/me/transactions/{deposit.id}",
    ]
    state["actor"] = CurrentActor(pending, "CBS", ActorType.CUSTOMER)
    assert client.get("/me").json()["link_status"] == "PENDING_LINK"
    for path in paths:
        result = client.get(path)
        assert result.status_code == 403 and result.json()["detail"] == "Customer link required"
    state["actor"] = CurrentActor(actor_a, "CBS", ActorType.ADMIN)
    assert all(client.get(path).status_code == 403 for path in paths)
    app.dependency_overrides.pop(get_current_actor)
    assert all(client.get(path).status_code == 401 for path in paths)
