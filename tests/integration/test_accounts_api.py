from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from api.dependencies import get_account_number_generator
from api.main import create_app
from infrastructure.settings import Settings
from tests.account_fakes import FixedAccountNumberGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
def app(migrated_engine, isolated_database_settings):
    return create_app(
        Settings(
            persistence_backend="postgres",
            database_url=isolated_database_settings.database_url,
            _env_file=None,
        )
    )


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_all_endpoints_persist_with_application_transaction_boundaries(
    client, app, migrated_engine
):
    commits = []

    def committed(session):
        commits.append(True)

    event.listen(Session, "after_commit", committed)
    try:
        response = client.post("/accounts", json={"customer_id": str(uuid4())})
        assert response.status_code == 201, response.text
        account = response.json()
        account_id = UUID(account["id"])
        assert account["product_type"] == "SAVINGS_ACCOUNT"
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT status FROM banking.accounts WHERE id = :id"), {"id": account_id}
                )
                == "ACTIVE"
            )
        assert client.get(f"/accounts/{account_id}").json() == account
        assert client.get(f"/accounts/by-number/{account['account_number']}").json() == account
        listing = client.get("/accounts").json()
        assert listing["items"] == [account]
        assert listing["pagination"]["total_items"] == 1
        assert len(commits) == 1  # HTTP reads never commit.

        blocked = client.patch(f"/accounts/{account_id}/block")
        assert blocked.status_code == 200 and blocked.json()["status"] == "BLOCKED"
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT status FROM banking.accounts WHERE id = :id"), {"id": account_id}
                )
                == "BLOCKED"
            )
        assert client.patch(f"/accounts/{account_id}/block").status_code == 409
        active = client.patch(f"/accounts/{account_id}/reactivate")
        assert active.status_code == 200 and active.json()["status"] == "ACTIVE"
        assert client.get(f"/accounts/{account_id}").json() == active.json()
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT status FROM banking.accounts WHERE id = :id"), {"id": account_id}
                )
                == "ACTIVE"
            )
        assert len(commits) == 3
        assert app.state.session_factory.kw["bind"].pool.checkedout() == 0
    finally:
        event.remove(Session, "after_commit", committed)


def test_duplicate_number_is_409_rolls_back_and_releases_session(client, app, migrated_engine):
    numbers = FixedAccountNumberGenerator("000-Internal-000001")
    app.dependency_overrides[get_account_number_generator] = lambda: numbers
    payload = {"customer_id": str(uuid4())}
    first = client.post("/accounts", json=payload)
    assert first.status_code == 201
    second = client.post("/accounts", json=payload)
    assert second.status_code == 409
    assert second.json() == {"detail": "Account number already in use"}
    assert numbers.calls == 2
    assert client.get("/accounts/by-number/000-Internal-000001").json() == first.json()
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM banking.accounts")) == 1
    assert app.state.session_factory.kw["bind"].pool.checkedout() == 0


def test_filtered_counts_and_pagination_are_correct_in_postgresql(client, migrated_engine):
    customer = str(uuid4())
    accounts = []
    for i in range(4):
        response = client.post(
            "/accounts", json={"customer_id": customer if i != 2 else str(uuid4())}
        )
        assert response.status_code == 201
        accounts.append(response.json())
    expected = sorted(
        (item for item in accounts if item["customer_id"] == customer), key=lambda row: row["id"]
    )
    response = client.get("/accounts", params={"customer_id": customer, "limit": 1, "offset": 1})
    assert response.status_code == 200
    assert response.json() == {
        "items": expected[1:2],
        "pagination": {"limit": 1, "offset": 1, "total_items": 3, "total_pages": 3},
    }
    assert client.get("/accounts").json()["pagination"]["total_items"] == 4


def test_closed_missing_and_invalid_requests_do_not_commit(client, app, migrated_engine):
    response = client.post("/accounts", json={"customer_id": str(uuid4())})
    account = response.json()
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE banking.accounts SET status = 'CLOSED', closed_at = opened_at "
                "WHERE id = :id"
            ),
            {"id": UUID(account["id"])},
        )
    commits = []

    def committed(session):
        commits.append(True)

    event.listen(Session, "after_commit", committed)
    try:
        assert client.patch(f"/accounts/{account['id']}/reactivate").status_code == 409
        assert client.patch(f"/accounts/{uuid4()}/block").status_code == 404
        assert client.get(f"/accounts/{uuid4()}").status_code == 404
        assert (
            client.post(
                "/accounts", json={"customer_id": str(uuid4()), "currency": "czk"}
            ).status_code
            == 422
        )
        assert client.get("/accounts", params={"limit": 0}).status_code == 422
        assert client.get(f"/accounts/{account['id']}").json()["status"] == "CLOSED"
        assert commits == []
        assert app.state.session_factory.kw["bind"].pool.checkedout() == 0
    finally:
        event.remove(Session, "after_commit", committed)
