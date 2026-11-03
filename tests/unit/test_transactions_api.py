from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from api import dependencies
from api.main import create_app
from application.transaction_messages import CreateDepositCommand
from application.use_cases.create_deposit import CreateDeposit
from domain.account_balance.exceptions import InvalidAccountBalanceData
from infrastructure.settings import Settings
from tests.account_fakes import FakeAccountUnitOfWork


@pytest.fixture
def work():
    return FakeAccountUnitOfWork()


@pytest.fixture
def app(work):
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[dependencies.get_account_unit_of_work] = lambda: work
    return app


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def create(client):
    result = client.post("/accounts", json={"customer_id": str(uuid4())})
    assert result.status_code == 201
    return result.json()["id"]


def write(client, kind, account_id, amount="10.00", key="key", **extra):
    return client.post(
        f"/transactions/{kind}",
        headers={"Idempotency-Key": key},
        json={
            "account_id": account_id,
            "amount": amount,
            "currency": "CZK",
            **extra,
        },
    )


def test_all_routes_and_safe_monetary_contracts(client, work):
    a, b = create(client), create(client)
    deposited = write(client, "deposits", a, "500.00")
    assert deposited.status_code == 201, deposited.text
    body = deposited.json()
    assert body["transaction_type"] == "DEPOSIT" and body["status"] == "POSTED"
    assert body["amount"] == "500.00" and body["description"] is None
    assert body["idempotency_key"] == "key" and body["reversal_of_id"] is None
    UUID(body["id"])
    for field in ("created_at", "effective_at", "posted_at"):
        assert datetime.fromisoformat(body[field]).utcoffset() is not None
    withdrawal = write(client, "withdrawals", a, "200.00", "withdraw", description="cash")
    assert withdrawal.status_code == 201 and withdrawal.json()["description"] == "cash"
    transfer = client.post(
        "/transactions/transfers",
        headers={"Idempotency-Key": "transfer"},
        json={
            "source_account_id": a,
            "destination_account_id": b,
            "amount": "100.00",
            "currency": "CZK",
        },
    )
    assert transfer.status_code == 201, transfer.text
    assert client.get(f"/transactions/{body['id']}").json() == body
    assert client.get(f"/accounts/{a}/balance").json()["booked_balance"] == "200.00"
    assert client.get(f"/accounts/{b}/balance").json()["available_balance"] == "100.00"
    effects = client.get(f"/accounts/{a}/movements").json()
    assert effects["pagination"] == {"limit": 50, "offset": 0, "total_items": 3, "total_pages": 1}
    assert {m["direction"] for m in effects["items"]} == {"CREDIT", "DEBIT"}
    assert all(
        isinstance(m["amount"], str) and isinstance(m["balance_after"], str)
        for m in effects["items"]
    )
    before = work.commits
    listed = client.get(
        "/transactions", params={"transaction_type": "DEPOSIT", "status": "POSTED", "limit": 1}
    ).json()
    assert listed["items"] == [body] and listed["pagination"]["total_items"] == 1
    assert client.get("/transactions", params={"offset": 100}).json()["items"] == []
    assert (
        client.get(f"/accounts/{b}/movements", params={"limit": 1, "offset": 1}).json()["items"]
        == []
    )
    assert work.commits == before


@pytest.mark.parametrize(
    "amount", ["0", "-1", "0.001", "NaN", "Infinity", "10000000000000000", "", None, 12, 1.23, True]
)
@pytest.mark.parametrize("kind", ["deposits", "withdrawals", "transfers"])
def test_invalid_money_never_reaches_application(client, work, amount, kind):
    payload = {"amount": amount, "currency": "CZK", "account_id": str(uuid4())}
    if kind == "transfers":
        payload.pop("account_id")
        payload.update(source_account_id=str(uuid4()), destination_account_id=str(uuid4()))
    response = client.post(
        f"/transactions/{kind}", headers={"Idempotency-Key": "key"}, json=payload
    )
    assert response.status_code == 422, response.text
    assert work.entries == 0


@pytest.mark.parametrize("header", [None, "", " ", "a" * 101])
@pytest.mark.parametrize("kind", ["deposits", "withdrawals", "transfers"])
def test_header_required_and_validated(client, work, header, kind):
    payload = {"amount": "1.00", "currency": "CZK", "account_id": str(uuid4())}
    if kind == "transfers":
        payload.pop("account_id")
        payload.update(source_account_id=str(uuid4()), destination_account_id=str(uuid4()))
    response = client.post(
        f"/transactions/{kind}",
        headers={} if header is None else {"Idempotency-Key": header},
        json=payload,
    )
    assert response.status_code == 422
    assert work.entries == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "POSTED"},
        {"balance_after": "100"},
        {"idempotency_key": "body-key"},
        {"amount": "1.001"},
        {"account_id": "bad"},
        {"currency": "czk"},
        {"currency": "CZK\n"},
        {"description": 123},
    ],
)
def test_invalid_contract_and_server_fields(client, work, extra):
    response = client.post(
        "/transactions/deposits",
        headers={"Idempotency-Key": "key"},
        json={"account_id": str(uuid4()), "amount": "10.00", "currency": "CZK", **extra},
    )
    assert response.status_code == 422
    assert work.entries == 0


def test_same_account_transfer_is_422(client, work):
    account = str(uuid4())
    response = client.post(
        "/transactions/transfers",
        headers={"Idempotency-Key": "key"},
        json={
            "source_account_id": account,
            "destination_account_id": account,
            "amount": "1.00",
            "currency": "CZK",
        },
    )
    assert response.status_code == 422
    assert work.entries == 0


def test_business_errors_and_idempotency(client, work):
    a = create(client)
    original = write(client, "deposits", a)
    assert write(client, "deposits", a, "10.0000").json() == original.json()
    assert write(client, "deposits", a, "11").status_code == 409
    assert write(client, "withdrawals", a, "1", "key").status_code == 409
    assert write(client, "withdrawals", a, "11", "funds").json() == {"detail": "Insufficient funds"}
    assert write(client, "deposits", a, key="currency", currency="EUR").status_code == 422
    assert write(client, "deposits", str(uuid4()), key="unknown").status_code == 404
    assert client.get(f"/transactions/{uuid4()}").status_code == 404
    assert client.get(f"/accounts/{uuid4()}/movements").status_code == 404
    assert client.get(f"/accounts/{uuid4()}/balance").status_code == 404
    assert client.patch(f"/accounts/{a}/block").status_code == 200
    assert write(client, "deposits", a, key="blocked").status_code == 409
    assert write(client, "deposits", a).json() == original.json()
    assert client.patch(f"/accounts/{a}/reactivate").status_code == 200
    del work.balances.rows[UUID(a)]
    assert client.get(f"/accounts/{a}/balance").status_code == 409


@pytest.mark.parametrize(
    "path", ["/transactions", "/accounts/00000000-0000-0000-0000-000000000000/movements"]
)
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "abc"}])
def test_invalid_pagination(client, path, params):
    assert client.get(path, params=params).status_code == 422


@pytest.mark.parametrize("params", [{"transaction_type": "BAD"}, {"status": "posted"}])
def test_invalid_filters(client, params):
    assert client.get("/transactions", params=params).status_code == 422


@pytest.mark.parametrize(
    "error,code,detail",
    [
        (RuntimeError("private SQL credentials"), 500, "Internal server error"),
        (
            OperationalError("private SQL", {}, Exception("password")),
            503,
            "Database operation unavailable",
        ),
        (InvalidAccountBalanceData("private"), 422, "Operation would produce an invalid balance"),
    ],
)
def test_failures_redacted_and_rolled_back(client, work, error, code, detail):
    a = create(client)
    work.commit_error = error
    response = write(client, "deposits", a)
    assert response.status_code == code and response.json() == {"detail": detail}
    assert not work.transactions.rows and not work.movements.rows
    assert work.balances.rows[UUID(a)].booked_balance == 0


def test_routes_use_injected_application_service(client, app, work):
    a = create(client)
    service = Mock(wraps=CreateDeposit(work))
    app.dependency_overrides[dependencies.get_create_deposit] = lambda: service
    assert write(client, "deposits", a).status_code == 201
    service.execute.assert_called_once_with(
        CreateDepositCommand(UUID(a), Decimal("10.00"), "CZK", "key")
    )


def test_openapi_documents_seven_endpoints_and_string_money(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    for path in ("deposits", "withdrawals", "transfers"):
        operation = paths[f"/transactions/{path}"]["post"]
        assert operation["tags"] == ["Transactions"]
        assert {"201", "404", "409", "422", "500", "503"} <= operation["responses"].keys()
        header = next(p for p in operation["parameters"] if p["in"] == "header")
        assert header["name"] == "Idempotency-Key" and header["required"] is True
    for path in (
        "/transactions",
        "/transactions/{transaction_id}",
        "/accounts/{account_id}/movements",
        "/accounts/{account_id}/balance",
    ):
        assert paths[path]["get"]["tags"] == ["Transactions"]
    models = schema["components"]["schemas"]
    assert models["DepositRequest"]["properties"]["amount"]["type"] == "string"
    assert models["TransactionResponse"]["properties"]["amount"]["type"] == "string"
    assert models["DepositRequest"]["additionalProperties"] is False
    assert set(models["TransactionStatus"]["enum"]) == {"PENDING", "POSTED", "REJECTED", "REVERSED"}


def test_memory_backend_is_unavailable_without_false_success():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/transactions").status_code == 503
        assert client.get("/health").status_code == 200


def test_transaction_movements_include_transfer_sides_with_bounded_pagination(client):
    source, destination = create(client), create(client)
    assert write(client, "deposits", source, "100", "fund").status_code == 201
    result = client.post(
        "/transactions/transfers",
        headers={"Idempotency-Key": "transfer"},
        json={
            "source_account_id": source,
            "destination_account_id": destination,
            "amount": "10.00",
            "currency": "CZK",
        },
    )
    transaction_id = result.json()["id"]
    page = client.get(f"/transactions/{transaction_id}/movements", params={"limit": 1}).json()
    assert len(page["items"]) == 1
    assert page["pagination"] == {"limit": 1, "offset": 0, "total_items": 2, "total_pages": 2}
    following = client.get(
        f"/transactions/{transaction_id}/movements", params={"limit": 1, "offset": 1}
    ).json()
    assert {page["items"][0]["account_id"], following["items"][0]["account_id"]} == {
        source,
        destination,
    }
    assert client.get(f"/transactions/{uuid4()}/movements").status_code == 404
    assert (
        client.get(f"/transactions/{transaction_id}/movements", params={"limit": 101}).status_code
        == 422
    )
