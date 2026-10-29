from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from domain.account.entities import Account
from domain.account.enums import AccountProductType, AccountStatus
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.mappers import account_mapper
from infrastructure.persistence.models import AccountORM

pytestmark = pytest.mark.integration


@pytest.fixture
def account() -> Account:
    return Account(
        id=uuid4(),
        customer_id=uuid4(),
        account_number="0000123456",
        product_type=AccountProductType.SAVINGS_ACCOUNT,
        currency="EUR",
        status=AccountStatus.ACTIVE,
        opened_at=date(2024, 1, 1),
        created_at=datetime(2024, 1, 1, 9, 30, 1, 123456, tzinfo=UTC),
        updated_at=datetime(2024, 2, 1, 12, tzinfo=UTC),
    )


@pytest.mark.parametrize("status", list(AccountStatus))
def test_insert_read_and_map_all_fields(
    migrated_engine: Engine, account: Account, status: AccountStatus
) -> None:
    source = replace(
        account,
        status=status,
        closed_at=date(2024, 2, 1) if status is AccountStatus.CLOSED else None,
    )
    sessions = create_session_factory(migrated_engine)
    with sessions.begin() as session:
        session.add(account_mapper.to_orm(source))
    with sessions() as session:
        row = session.get(AccountORM, source.id)
        assert row is not None
        assert row.created_at.utcoffset() is not None
        assert row.updated_at.utcoffset() is not None
        assert row.product_type is AccountProductType.SAVINGS_ACCOUNT
        assert row.status is status
        assert account_mapper.to_domain(row) == source


def test_update_status_using_domain_transitions(migrated_engine: Engine, account: Account) -> None:
    sessions = create_session_factory(migrated_engine)
    with sessions.begin() as session:
        session.add(account_mapper.to_orm(account))
    for transition in (Account.block, Account.reactivate):
        with sessions.begin() as session:
            row = session.get(AccountORM, account.id)
            assert row is not None
            changed = transition(account_mapper.to_domain(row))
            row.status = changed.status
            row.updated_at = changed.updated_at
        with sessions() as session:
            row = session.get(AccountORM, account.id)
            assert row is not None
            assert account_mapper.to_domain(row) == changed


def _insert_sql(values: dict[str, object]) -> str:
    # Keys come only from this test's known Account fields, never external input.
    return (
        f"INSERT INTO banking.accounts ({', '.join(values)}) "
        f"VALUES ({', '.join(':' + name for name in values)})"
    )


def test_server_defaults_without_python_defaults(migrated_engine: Engine, account: Account) -> None:
    values = asdict(account)
    del values["product_type"], values["status"]
    with migrated_engine.begin() as connection:
        connection.execute(text(_insert_sql(values)), values)
        row = connection.execute(text("SELECT product_type, status FROM banking.accounts")).one()
        assert tuple(row) == ("SAVINGS_ACCOUNT", "ACTIVE")


def test_duplicate_account_number(migrated_engine: Engine, account: Account) -> None:
    values = asdict(account)
    with migrated_engine.begin() as connection:
        connection.execute(text(_insert_sql(values)), values)
    values["id"] = uuid4()
    with pytest.raises(IntegrityError) as error, migrated_engine.begin() as connection:
        connection.execute(text(_insert_sql(values)), values)
    assert error.value.orig.diag.constraint_name == "uq_accounts_account_number"


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"product_type": "CURRENT_ACCOUNT"}, "ck_accounts_product_type"),
        ({"product_type": "SAVING_ACCOUNT"}, "ck_accounts_product_type"),
        ({"product_type": "UNKNOWN"}, "ck_accounts_product_type"),
        ({"status": "UNKNOWN"}, "ck_accounts_status"),
        ({"status": "CLOSED"}, "ck_accounts_closed_at"),
        ({"closed_at": date(2024, 2, 1)}, "ck_accounts_closed_at"),
        ({"status": "BLOCKED", "closed_at": date(2024, 2, 1)}, "ck_accounts_closed_at"),
        (
            {"status": "CLOSED", "closed_at": date(2023, 12, 31)},
            "ck_accounts_lifecycle_dates",
        ),
        ({"account_number": ""}, "ck_accounts_account_number"),
        ({"account_number": " \t\n"}, "ck_accounts_account_number"),
        ({"currency": "eur"}, "ck_accounts_currency"),
        ({"currency": "EU"}, "ck_accounts_currency"),
        ({"currency": "E1R"}, "ck_accounts_currency"),
        ({"currency": "ÉUR"}, "ck_accounts_currency"),
    ],
)
def test_database_checks_bypass_python_validation(
    migrated_engine: Engine, account: Account, changes: dict[str, object], constraint: str
) -> None:
    values = asdict(account)
    values.update(changes)
    with pytest.raises(IntegrityError) as error, migrated_engine.begin() as connection:
        connection.execute(text(_insert_sql(values)), values)
    assert error.value.orig.diag.constraint_name == constraint


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "customer_id",
        "account_number",
        "product_type",
        "currency",
        "status",
        "opened_at",
        "created_at",
        "updated_at",
    ],
)
def test_database_not_null(migrated_engine: Engine, account: Account, field: str) -> None:
    values = asdict(account)
    values[field] = None
    with pytest.raises(IntegrityError) as error, migrated_engine.begin() as connection:
        connection.execute(text(_insert_sql(values)), values)
    assert error.value.orig.diag.column_name == field


def test_customer_index_and_query(migrated_engine: Engine, account: Account) -> None:
    indexes = inspect(migrated_engine).get_indexes("accounts", schema="banking")
    assert any(
        index["name"] == "ix_banking_accounts_customer_id"
        and index["column_names"] == ["customer_id"]
        for index in indexes
    )
    sessions = create_session_factory(migrated_engine)
    with sessions.begin() as session:
        session.add(account_mapper.to_orm(account))
    with sessions() as session:
        row = session.scalar(
            select(AccountORM).where(AccountORM.customer_id == account.customer_id)
        )
        assert row is not None and row.id == account.id
    # Prove the index is usable; on a one-row table the planner normally prefers a scan.
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = connection.scalars(
            text("EXPLAIN SELECT * FROM banking.accounts WHERE customer_id = :id"),
            {"id": account.customer_id},
        ).all()
        assert "ix_banking_accounts_customer_id" in " ".join(plan)
