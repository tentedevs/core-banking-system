from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from api.authentication import require_banking_admin
from api.main import create_app
from application.account_balance_service import AccountBalanceService
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.repositories.account_movement_repository import (
    SQLAlchemyAccountMovementRepository,
)
from infrastructure.persistence.repositories.transaction_repository import (
    SQLAlchemyTransactionRepository,
)
from infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def app(migrated_engine, isolated_database_settings):
    app = create_app(
        Settings(
            persistence_backend="postgres",
            database_url=isolated_database_settings.database_url,
            _env_file=None,
        )
    )

    app.dependency_overrides[require_banking_admin] = lambda: None
    return app


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def accounts(client):
    result = []
    for _ in range(2):
        response = client.post("/accounts", json={"customer_id": str(uuid4())})
        assert response.status_code == 201
        result.append(response.json())
    return result


def money(client, kind, account, amount="10.00", key="key", destination=None, **extra):
    payload = {"amount": amount, "currency": "CZK", "description": None}
    if kind == "transfers":
        payload.update(source_account_id=account["id"], destination_account_id=destination["id"])
    else:
        payload["account_id"] = account["id"]
    return client.post(
        f"/transactions/{kind}", headers={"Idempotency-Key": key}, json={**payload, **extra}
    )


def counts(engine):
    with engine.connect() as connection:
        return tuple(
            connection.scalar(text(f"SELECT count(*) FROM banking.{name}"))
            for name in ("transactions", "account_movements", "transaction_requests")
        )


def balance(client, account):
    result = client.get(f"/accounts/{account['id']}/balance")
    assert result.status_code == 200, result.text
    return result.json()


def reconcile(app, accounts):
    with SQLAlchemyAccountUnitOfWork(app.state.session_factory) as work:
        coordinator = AccountBalanceService(work.accounts, work.balances)
        for account in accounts:
            assert coordinator.check_consistency(
                UUID(account["id"]), currency=account["currency"]
            ).is_consistent


def test_all_endpoints_commit_together_reads_never_commit_and_release_sessions(
    client, app, migrated_engine
):
    commits = []

    def committed(session):
        commits.append(True)

    event.listen(Session, "after_commit", committed)
    try:
        accounts = [
            client.post("/accounts", json={"customer_id": str(uuid4())}).json() for _ in range(2)
        ]
        a, b = accounts
        deposited = money(client, "deposits", a, "500.00", "deposit", description="simulated cash")
        withdrawn = money(client, "withdrawals", a, "200.00", "withdrawal")
        transferred = money(client, "transfers", a, "100.00", "transfer", b)
        for result in (deposited, withdrawn, transferred):
            assert result.status_code == 201, result.text
            assert result.json()["status"] == "POSTED"
            assert client.get("/transactions/" + result.json()["id"]).json() == result.json()
        assert len(commits) == 5
        assert (
            balance(client, a)["booked_balance"]
            == balance(client, a)["available_balance"]
            == "200.00"
        )
        assert balance(client, b)["available_balance"] == "100.00"
        source = client.get(f"/accounts/{a['id']}/movements").json()
        destination = client.get(f"/accounts/{b['id']}/movements").json()
        assert source["pagination"]["total_items"] == 3
        assert destination["pagination"]["total_items"] == 1
        effects = source["items"] + destination["items"]
        expected = {
            deposited.json()["id"]: [("CREDIT", "500.00")],
            withdrawn.json()["id"]: [("DEBIT", "300.00")],
            transferred.json()["id"]: [("DEBIT", "200.00"), ("CREDIT", "100.00")],
        }
        for transaction_id, values in expected.items():
            assert [
                (m["direction"], m["balance_after"])
                for m in effects
                if m["transaction_id"] == transaction_id
            ] == values
        assert client.get("/transactions").json()["pagination"]["total_items"] == 3
        assert counts(migrated_engine) == (3, 4, 3)
        reconcile(app, accounts)
        assert len(commits) == 5
        assert app.state.session_factory.kw["bind"].pool.checkedout() == 0
    finally:
        event.remove(Session, "after_commit", committed)


@pytest.mark.parametrize("kind", ["deposits", "withdrawals", "transfers"])
def test_retries_original_results_conflicts_and_no_extra_commits(
    client, accounts, app, migrated_engine, kind
):
    a, b = accounts
    assert money(client, "deposits", a, "100", "fund").status_code == 201
    first = money(client, kind, a, key="stable", destination=b)
    assert first.status_code == 201, first.text
    before = [balance(client, account) for account in accounts]
    before_counts = counts(migrated_engine)
    commits = []

    def committed(session):
        commits.append(True)

    event.listen(Session, "after_commit", committed)
    try:
        retry = money(client, kind, a, "10.0000", "stable", b)
        assert retry.status_code == 201 and retry.json() == first.json()
        different = money(client, kind, a, "11", "stable", b)
        assert different.status_code == 409
        assert different.json() == {"detail": "Idempotency key conflicts with the original request"}
        assert [balance(client, account) for account in accounts] == before
        assert counts(migrated_engine) == before_counts and commits == []
        reconcile(app, accounts)
        assert app.state.session_factory.kw["bind"].pool.checkedout() == 0
    finally:
        event.remove(Session, "after_commit", committed)


@pytest.mark.parametrize("kind", ["withdrawals", "transfers"])
def test_insufficient_funds_no_partial_effects(client, accounts, app, migrated_engine, kind):
    a, b = accounts
    result = money(client, kind, a, destination=b)
    assert result.status_code == 409 and result.json() == {"detail": "Insufficient funds"}
    assert counts(migrated_engine) == (0, 0, 0)
    assert balance(client, a)["booked_balance"] == balance(client, b)["booked_balance"] == "0.00"
    assert money(client, "deposits", a, "20", "funding").status_code == 201
    assert money(client, kind, a, destination=b).status_code == 201
    reconcile(app, accounts)
    assert app.state.session_factory.kw["bind"].pool.checkedout() == 0


@pytest.mark.parametrize("kind", ["deposits", "withdrawals", "transfers"])
@pytest.mark.parametrize("status", ["BLOCKED", "CLOSED"])
def test_inactive_accounts_rejected_and_accounts_api_remains_available(
    client, accounts, app, migrated_engine, kind, status
):
    a, b = accounts
    assert money(client, "deposits", a, "100", "fund").status_code == 201
    if status == "BLOCKED":
        assert client.patch(f"/accounts/{a['id']}/block").status_code == 200
    else:
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE banking.accounts SET status = 'CLOSED', "
                    "closed_at = opened_at WHERE id = :id"
                ),
                {"id": UUID(a["id"])},
            )
    result = money(client, kind, a, destination=b)
    assert result.status_code == 409 and result.json() == {"detail": "Account must be ACTIVE"}
    assert client.get(f"/accounts/{a['id']}").json()["status"] == status
    assert counts(migrated_engine) == (1, 1, 1)
    assert balance(client, a)["booked_balance"] == "100.00"
    if status == "BLOCKED":
        assert client.patch(f"/accounts/{a['id']}/reactivate").status_code == 200
        assert money(client, kind, a, destination=b).status_code == 201
    reconcile(app, accounts)


def test_missing_currency_invalid_requests_and_uninitialized_balance(
    client, accounts, app, migrated_engine
):
    a, b = accounts
    missing = {"id": str(uuid4())}
    for kind in ("deposits", "withdrawals", "transfers"):
        assert money(client, kind, missing, destination=b).status_code == 404
        assert money(client, kind, a, destination=b, currency="EUR").status_code == 422
        assert money(client, kind, a, amount="0", destination=b).status_code == 422
    assert client.get(f"/transactions/{uuid4()}").status_code == 404
    assert client.get(f"/accounts/{missing['id']}/balance").status_code == 404
    assert client.get(f"/accounts/{missing['id']}/movements").status_code == 404
    assert client.get("/transactions/not-a-uuid").status_code == 422
    assert client.get("/transactions", params={"limit": 0}).status_code == 422
    assert client.get("/transactions", params={"transaction_type": "BAD"}).status_code == 422
    assert (
        client.post(
            "/transactions/deposits", json={"account_id": a["id"], "amount": "1", "currency": "CZK"}
        ).status_code
        == 422
    )
    for field in ("status", "balance_after"):
        assert money(client, "deposits", a, **{field: "POSTED"}).status_code == 422
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM banking.account_balance_openings WHERE account_id = :id"),
            {"id": UUID(b["id"])},
        )
        connection.execute(
            text("DELETE FROM banking.account_balances WHERE account_id = :id"),
            {"id": UUID(b["id"])},
        )
    assert client.get(f"/accounts/{b['id']}/balance").status_code == 409
    assert money(client, "deposits", b).status_code == 409
    assert counts(migrated_engine) == (0, 0, 0)
    assert app.state.session_factory.kw["bind"].pool.checkedout() == 0


def test_pagination_filtered_totals_stable_order_and_empty_pages(client, accounts, migrated_engine):
    a, b = accounts
    for index in range(3):
        assert money(client, "deposits", a, key=f"d{index}").status_code == 201
    assert money(client, "withdrawals", a, key="w").status_code == 201
    # Deliberate timestamp ties prove the UUID tie-breaker is part of the SQL order.
    with migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE banking.transactions SET created_at = '2026-01-01T00:00:00Z'")
        )
        connection.execute(
            text("UPDATE banking.account_movements SET booked_at = '2026-01-01T00:00:00Z'")
        )
    all_items = client.get("/transactions").json()["items"]
    assert [i["id"] for i in all_items] == sorted(i["id"] for i in all_items)
    expected = [i for i in all_items if i["transaction_type"] == "DEPOSIT"]
    page = client.get(
        "/transactions",
        params={"transaction_type": "DEPOSIT", "status": "POSTED", "limit": 1, "offset": 1},
    ).json()
    assert page == {
        "items": expected[1:2],
        "pagination": {"limit": 1, "offset": 1, "total_items": 3, "total_pages": 3},
    }
    assert (
        client.get("/transactions", params={"status": "PENDING"}).json()["pagination"][
            "total_items"
        ]
        == 0
    )
    assert (
        client.get("/transactions", params={"offset": 100}).json()["pagination"]["total_items"] == 4
    )
    effects = client.get(f"/accounts/{a['id']}/movements").json()["items"]
    assert [i["id"] for i in effects] == sorted(i["id"] for i in effects)
    assert client.get(
        f"/accounts/{a['id']}/movements", params={"limit": 2, "offset": 1}
    ).json() == {
        "items": effects[1:3],
        "pagination": {"limit": 2, "offset": 1, "total_items": 4, "total_pages": 2},
    }
    assert client.get(f"/accounts/{b['id']}/movements").json() == {
        "items": [],
        "pagination": {"limit": 50, "offset": 0, "total_items": 0, "total_pages": 0},
    }


@pytest.mark.parametrize("failure", ["unexpected", "foreign_key", "commit"])
def test_write_failures_are_redacted_rollback_and_release_session(
    client, accounts, app, migrated_engine, failure
):
    a, b = accounts
    assert money(client, "deposits", a, "100", "fund").status_code == 201
    if failure == "foreign_key":
        original = SQLAlchemyAccountMovementRepository.add

        def fail(self, movement):
            original(self, replace(movement, account_id=uuid4()))

        target, method = SQLAlchemyAccountMovementRepository, "add"
    else:

        def fail(self, *args):
            raise RuntimeError("private SQL password=secret")

        target, method = (
            (SQLAlchemyTransactionRepository, "record_request")
            if failure == "unexpected"
            else (SQLAlchemyAccountUnitOfWork, "commit")
        )
    with patch.object(target, method, fail):
        response = money(client, "transfers", a, destination=b)
    expected = 503 if failure == "foreign_key" else 500
    assert response.status_code == expected
    assert response.json() == {
        "detail": "Database operation unavailable" if expected == 503 else "Internal server error"
    }
    assert counts(migrated_engine) == (1, 1, 1)
    assert balance(client, a)["available_balance"] == "100.00"
    assert balance(client, b)["available_balance"] == "0.00"
    reconcile(app, accounts)
    assert app.state.session_factory.kw["bind"].pool.checkedout() == 0
    assert money(client, "transfers", a, destination=b).status_code == 201


def test_concurrent_http_retry_executes_once(client, accounts, app, migrated_engine):
    gate = Barrier(2)

    def request():
        gate.wait(timeout=5)
        return money(client, "deposits", accounts[0], key="simultaneous")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request) for _ in range(2)]
        responses = [future.result(timeout=10) for future in futures]
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert counts(migrated_engine) == (1, 1, 1)
    assert balance(client, accounts[0])["booked_balance"] == "10.00"
    reconcile(app, accounts)
    assert app.state.session_factory.kw["bind"].pool.checkedout() == 0


def test_transaction_movements_lookup_pagination_and_session_cleanup(client, accounts, app):
    source, destination = accounts
    assert money(client, "deposits", source, "100", "fund").status_code == 201
    transferred = money(client, "transfers", source, destination=destination).json()
    first = client.get(f"/transactions/{transferred['id']}/movements", params={"limit": 1}).json()
    second = client.get(
        f"/transactions/{transferred['id']}/movements", params={"limit": 1, "offset": 1}
    ).json()
    assert first["pagination"]["total_items"] == second["pagination"]["total_items"] == 2
    effects = first["items"] + second["items"]
    assert {item["account_id"] for item in effects} == {source["id"], destination["id"]}
    assert {item["direction"] for item in effects} == {"CREDIT", "DEBIT"}
    assert all(item["transaction_id"] == transferred["id"] for item in effects)
    assert client.get(f"/transactions/{uuid4()}/movements").status_code == 404
    reconcile(app, accounts)
    assert app.state.session_factory.kw["bind"].pool.checkedout() == 0


def test_known_transaction_without_movements_returns_empty_page(client, app):
    from dataclasses import replace

    from domain.transaction.enums import TransactionStatus
    from tests.transaction_factories import transaction

    pending = replace(transaction(), status=TransactionStatus.REJECTED, posted_at=None)
    with SQLAlchemyAccountUnitOfWork(app.state.session_factory) as work:
        work.transactions.add(pending)
        work.commit()
    result = client.get(f"/transactions/{pending.id}/movements")
    assert result.status_code == 200
    assert result.json() == {
        "items": [],
        "pagination": {"limit": 50, "offset": 0, "total_items": 0, "total_pages": 0},
    }
    assert app.state.session_factory.kw["bind"].pool.checkedout() == 0
