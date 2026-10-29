from dataclasses import replace
from datetime import date, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from api import dependencies
from api.main import create_app
from api.schemas.account import AccountResponse
from application.account_messages import (
    BlockAccountCommand,
    CreateAccountCommand,
    GetAccountByNumberQuery,
    GetAccountQuery,
    ListAccountsQuery,
    ReactivateAccountCommand,
)
from application.use_cases.block_account import BlockAccount
from application.use_cases.create_account import CreateAccount
from application.use_cases.get_account import GetAccount
from application.use_cases.get_account_by_number import GetAccountByNumber
from application.use_cases.list_accounts import ListAccounts
from application.use_cases.reactivate_account import ReactivateAccount
from domain.account.entities import Account
from domain.account.enums import AccountStatus
from infrastructure.settings import Settings
from ports.account_repository import AccountNumberConflict
from tests.account_fakes import FakeAccountUnitOfWork, FixedAccountNumberGenerator


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


def create(client, **changes):
    response = client.post("/accounts", json={"customer_id": str(uuid4()), **changes})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_serializes_every_field_and_uses_defaults(client, work):
    body = create(client)
    assert set(body) == {
        "id",
        "customer_id",
        "account_number",
        "product_type",
        "currency",
        "status",
        "opened_at",
        "closed_at",
        "created_at",
        "updated_at",
    }
    assert UUID(body["id"]).version == 4
    assert isinstance(UUID(body["customer_id"]), UUID)
    assert body["product_type"] == "SAVINGS_ACCOUNT"
    assert body["status"] == "ACTIVE" and body["closed_at"] is None
    assert body["currency"] == "CZK"
    assert len(body["account_number"]) <= 34
    date.fromisoformat(body["opened_at"])
    for field in ("created_at", "updated_at"):
        assert datetime.fromisoformat(body[field]).utcoffset() is not None
    assert work.commits == 1


@pytest.mark.parametrize("currency", ["", "czk", "CZ", "EURO", "ÉUR", "CZK\n", None, 123])
def test_invalid_currency_is_422(client, currency):
    response = client.post("/accounts", json={"customer_id": str(uuid4()), "currency": currency})
    assert response.status_code == 422
    assert "detail" in response.json()


@pytest.mark.parametrize("customer_id", ["invalid", "", 123, None])
def test_invalid_customer_uuid(client, customer_id):
    assert client.post("/accounts", json={"customer_id": customer_id}).status_code == 422


@pytest.mark.parametrize(
    "field",
    ["id", "account_number", "product_type", "status", "opened_at", "created_at", "unknown"],
)
def test_creation_rejects_managed_or_unknown_fields(client, field):
    response = client.post("/accounts", json={"customer_id": str(uuid4()), field: "arbitrary"})
    assert response.status_code == 422


def test_get_and_by_number_preserve_formatting(client, app, work):
    generator = FixedAccountNumberGenerator("000-Example-0001")
    app.dependency_overrides[dependencies.get_account_number_generator] = lambda: generator
    body = create(client, currency="EUR")
    assert client.get(f"/accounts/{body['id']}").json() == body
    by_number = client.get("/accounts/by-number/000-Example-0001")
    assert by_number.status_code == 200 and by_number.json() == body
    assert work.commits == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/accounts/{id}"),
        ("get", "/accounts/by-number/unknown"),
        ("patch", "/accounts/{id}/block"),
        ("patch", "/accounts/{id}/reactivate"),
    ],
)
def test_missing_accounts_are_404(client, method, path):
    response = getattr(client, method)(path.format(id=uuid4()))
    assert response.status_code == 404
    assert response.json() == {"detail": "Account not found"}


@pytest.mark.parametrize("suffix", ["", "/block", "/reactivate"])
def test_invalid_path_uuid(client, suffix):
    method = client.patch if suffix else client.get
    assert method(f"/accounts/not-a-uuid{suffix}").status_code == 422


def test_empty_list_defaults(client, work):
    response = client.get("/accounts")
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "pagination": {"limit": 50, "offset": 0, "total_items": 0, "total_pages": 0},
    }
    assert work.commits == 0


def test_list_paginates_filters_and_counts_before_pagination(client, work):
    customer = uuid4()
    for i in (4, 1, 3, 2):
        row = Account.create(
            customer_id=customer if i != 2 else uuid4(),
            account_number=f"number-{i}",
            currency="CZK",
            opened_at=date(2024, 1, 1),
        )
        row = replace(row, id=UUID(int=i))
        work.accounts.rows[row.id] = row
    body = client.get("/accounts", params={"limit": 2, "offset": 1}).json()
    assert [item["id"] for item in body["items"]] == [str(UUID(int=2)), str(UUID(int=3))]
    assert body["pagination"] == {"limit": 2, "offset": 1, "total_items": 4, "total_pages": 2}
    filtered = client.get(
        "/accounts", params={"customer_id": str(customer), "limit": 1, "offset": 1}
    )
    assert [item["id"] for item in filtered.json()["items"]] == [str(UUID(int=3))]
    assert filtered.json()["pagination"]["total_items"] == 3
    beyond = client.get("/accounts", params={"offset": 100}).json()
    assert beyond["items"] == [] and beyond["pagination"]["total_items"] == 4
    unknown = client.get("/accounts", params={"customer_id": str(uuid4())}).json()
    assert unknown["items"] == [] and unknown["pagination"]["total_items"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": "abc"},
        {"limit": 1.5},
        {"offset": -1},
        {"offset": 1.5},
        {"offset": "abc"},
        {"customer_id": "invalid"},
    ],
)
def test_invalid_list_inputs(client, params):
    assert client.get("/accounts", params=params).status_code == 422


def test_block_and_reactivate_commit_only_through_application(client, work):
    body = create(client)
    account_id = body["id"]
    assert client.patch(f"/accounts/{account_id}/reactivate").status_code == 409
    blocked = client.patch(f"/accounts/{account_id}/block")
    assert blocked.status_code == 200 and blocked.json()["status"] == "BLOCKED"
    assert client.patch(f"/accounts/{account_id}/block").status_code == 409
    active = client.patch(f"/accounts/{account_id}/reactivate")
    assert active.status_code == 200 and active.json()["status"] == "ACTIVE"
    assert work.commits == 3
    assert client.get(f"/accounts/{account_id}").json() == active.json()


def test_closed_accounts_cannot_be_reactivated(client, work):
    body = create(client)
    account_id = UUID(body["id"])
    work.accounts.rows[account_id] = replace(
        work.accounts.rows[account_id],
        status=AccountStatus.CLOSED,
        closed_at=work.accounts.rows[account_id].opened_at,
    )
    assert client.patch(f"/accounts/{account_id}/reactivate").status_code == 409
    assert client.patch(f"/accounts/{account_id}/block").status_code == 409
    assert client.get(f"/accounts/{account_id}").json()["status"] == "CLOSED"


@pytest.mark.parametrize(
    ("error", "code", "detail"),
    [
        (AccountNumberConflict("private detail"), 409, "Account number already in use"),
        (
            OperationalError("private SQL", {}, Exception("private credentials")),
            503,
            "Database operation unavailable",
        ),
        (RuntimeError("private credentials"), 500, "Internal server error"),
    ],
)
def test_known_and_unexpected_failures_are_redacted(client, work, error, code, detail):
    work.commit_error = error
    response = client.post("/accounts", json={"customer_id": str(uuid4())})
    assert response.status_code == code
    assert response.json() == {"detail": detail}
    assert work.accounts.rows == {}


def test_disabled_backend_returns_503_and_health_remains_live():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/accounts").status_code == 503
        assert client.get("/health").json() == {"status": "ok"}


def test_routes_invoke_injected_services(app, client, work):
    services = {
        dependencies.get_create_account: Mock(wraps=CreateAccount(work)),
        dependencies.get_get_account: Mock(wraps=GetAccount(work)),
        dependencies.get_get_account_by_number: Mock(wraps=GetAccountByNumber(work)),
        dependencies.get_list_accounts: Mock(wraps=ListAccounts(work)),
        dependencies.get_block_account: Mock(wraps=BlockAccount(work)),
        dependencies.get_reactivate_account: Mock(wraps=ReactivateAccount(work)),
    }

    def override_factory(value):
        def override():
            return value

        return override

    for dependency, service in services.items():
        app.dependency_overrides[dependency] = override_factory(service)
    customer_id = uuid4()
    body = create(client, customer_id=str(customer_id))
    services[dependencies.get_create_account].execute.assert_called_once_with(
        CreateAccountCommand(customer_id)
    )
    account_id = UUID(body["id"])
    client.get(f"/accounts/{account_id}")
    services[dependencies.get_get_account].execute.assert_called_once_with(
        GetAccountQuery(account_id)
    )
    client.get(f"/accounts/by-number/{body['account_number']}")
    services[dependencies.get_get_account_by_number].execute.assert_called_once_with(
        GetAccountByNumberQuery(body["account_number"])
    )
    client.get("/accounts", params={"limit": 2, "offset": 1})
    services[dependencies.get_list_accounts].execute_with_total.assert_called_once_with(
        ListAccountsQuery(limit=2, offset=1)
    )
    client.patch(f"/accounts/{account_id}/block")
    services[dependencies.get_block_account].execute.assert_called_once_with(
        BlockAccountCommand(account_id)
    )
    client.patch(f"/accounts/{account_id}/reactivate")
    services[dependencies.get_reactivate_account].execute.assert_called_once_with(
        ReactivateAccountCommand(account_id)
    )


def test_openapi_documents_routes_models_and_errors(client):
    schema = client.get("/openapi.json").json()
    operations = [
        schema["paths"]["/accounts"]["post"],
        schema["paths"]["/accounts"]["get"],
        schema["paths"]["/accounts/{account_id}"]["get"],
        schema["paths"]["/accounts/by-number/{account_number}"]["get"],
        schema["paths"]["/accounts/{account_id}/block"]["patch"],
        schema["paths"]["/accounts/{account_id}/reactivate"]["patch"],
    ]
    assert all(operation["tags"] == ["Accounts"] for operation in operations)
    assert "409" in operations[0]["responses"]
    assert "404" in operations[2]["responses"]
    assert "422" in operations[0]["responses"]
    assert schema["components"]["schemas"]["AccountProductType"]["enum"] == ["SAVINGS_ACCOUNT"]
    assert schema["components"]["schemas"]["AccountCreateRequest"]["additionalProperties"] is False


def test_response_requires_aware_audit_timestamps():
    account = Account.create(
        customer_id=uuid4(), account_number="test", currency="CZK", opened_at=date(2024, 1, 1)
    )
    with pytest.raises(ValidationError):
        AccountResponse.model_validate(replace(account, created_at=datetime(2024, 1, 1)))
