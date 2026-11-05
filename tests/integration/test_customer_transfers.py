from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from auth_client import ActorType, CurrentActor
from sqlalchemy import select

from application.transaction_messages import CreateTransferCommand
from application.use_cases.create_customer_transfer import CreateCustomerTransfer
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.models import AccountBalanceORM
from tests.integration.test_customer_reads import customer_banking as customer_banking

pytestmark = pytest.mark.integration


def write(client, source, destination, key="customer-transfer", amount="10.00"):
    return client.post(
        "/me/transfers",
        headers={"Idempotency-Key": key},
        json={
            "source_account_id": str(source),
            "destination_account_id": str(destination),
            "amount": amount,
            "currency": "CZK",
            "description": None,
        },
    )


def balances(engine):
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(AccountBalanceORM.account_id, AccountBalanceORM.booked_balance)
            ).all()
        )


def test_customer_transfer_retries_and_private_response(customer_banking, migrated_engine):
    client, _, (source, _, destination), _, _, _, _ = customer_banking
    before = balances(migrated_engine)
    result = write(client, source.id, destination.id)
    assert result.status_code == 201
    assert "idempotency_key" not in result.json() and str(destination.id) not in result.text
    again = write(client, source.id, destination.id)
    assert again.status_code == 201 and again.json() == result.json()
    after = balances(migrated_engine)
    assert after[source.id] == before[source.id] - Decimal("10")
    assert after[destination.id] == before[destination.id] + Decimal("10")
    assert write(client, source.id, destination.id, amount="11.00").status_code == 409
    assert client.get(f"/me/accounts/{destination.id}/balance").status_code == 404


def test_unauthorized_transfers_and_admin_mutations_leave_balances_unchanged(
    customer_banking, migrated_engine
):
    client, state, (source, _, destination), _, (actor_a, _, pending), _, _ = customer_banking
    before = balances(migrated_engine)
    assert write(client, destination.id, source.id).status_code == 404
    state["actor"] = CurrentActor(pending, "CBS", ActorType.CUSTOMER)
    assert write(client, source.id, destination.id).status_code == 403
    state["actor"] = CurrentActor(actor_a, "CBS", ActorType.CUSTOMER)
    for path in (
        "/transactions/deposits",
        "/transactions/withdrawals",
        "/transactions/transfers",
        "/accounts",
    ):
        assert client.post(path).status_code == 403
    assert client.patch(f"/accounts/{source.id}/block").status_code == 403
    assert write(client, source.id, destination.id, amount="99999.00").status_code == 409
    assert balances(migrated_engine) == before


def test_receipt_cannot_bypass_current_ownership(customer_banking, migrated_engine):
    client, state, (source, _, destination), _, (_, actor_b, _), _, _ = customer_banking
    assert write(client, source.id, destination.id).status_code == 201
    before = balances(migrated_engine)
    state["actor"] = CurrentActor(actor_b, "CBS", ActorType.CUSTOMER)
    assert write(client, source.id, destination.id).status_code == 404
    assert balances(migrated_engine) == before


def test_customer_transfers_preserve_concurrent_atomicity(customer_banking, migrated_engine):
    _, _, (source, _, destination), _, (actor_a, actor_b, _), _, _ = customer_banking
    sessions = create_session_factory(migrated_engine)
    before = balances(migrated_engine)

    def execute(actor_id, src, dst):
        return CreateCustomerTransfer(SQLAlchemyAccountUnitOfWork(sessions)).execute(
            CurrentActor(actor_id, "CBS", ActorType.CUSTOMER),
            CreateTransferCommand(src, dst, Decimal("10"), "CZK", str(uuid4())),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(execute, actor_a, source.id, destination.id)
        b = pool.submit(execute, actor_b, destination.id, source.id)
        assert a.result(timeout=15).id != b.result(timeout=15).id
    assert balances(migrated_engine) == before
