from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from domain.account.entities import Account
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.mappers import (
    account_mapper,
    account_movement_mapper,
    transaction_mapper,
)
from infrastructure.persistence.models import AccountMovementORM, TransactionORM
from tests.transaction_factories import movement, transaction

pytestmark = pytest.mark.integration


@pytest.fixture
def records(migrated_engine):
    original = transaction()
    account = Account.create(
        customer_id=uuid4(), account_number="000-test", currency="CZK", opened_at=date(2024, 1, 1)
    )
    effect = movement(original.id, account.id)
    sessions = create_session_factory(migrated_engine)
    with sessions.begin() as session:
        session.add(account_mapper.to_orm(account))
        session.add(transaction_mapper.to_orm(original))
        session.flush()
        session.add(account_movement_mapper.to_orm(effect))
    return original, account, effect


@pytest.mark.parametrize("kind", list(TransactionType))
@pytest.mark.parametrize("status", list(TransactionStatus))
def test_transaction_database_round_trip(migrated_engine, kind, status):
    source = transaction()
    source = replace(
        source,
        transaction_type=kind,
        status=status,
        posted_at=source.posted_at
        if status in (TransactionStatus.POSTED, TransactionStatus.REVERSED)
        else None,
    )
    sessions = create_session_factory(migrated_engine)
    with sessions.begin() as session:
        session.add(transaction_mapper.to_orm(source))
    with sessions() as session:
        row = session.get(TransactionORM, source.id)
        assert transaction_mapper.to_domain(row) == source
        assert row.amount == Decimal("123.45")
        assert row.effective_at.utcoffset() is not None


@pytest.mark.parametrize("direction", list(MovementDirection))
def test_movement_database_round_trip(migrated_engine, records, direction):
    original, account, effect = records
    source = replace(
        effect,
        id=uuid4(),
        direction=direction,
        balance_after=Decimal("-9999999999999999.99"),
        amount=Decimal("9999999999999999.99"),
    )
    sessions = create_session_factory(migrated_engine)
    with sessions.begin() as session:
        session.add(account_movement_mapper.to_orm(source))
    with sessions() as session:
        assert (
            account_movement_mapper.to_domain(session.get(AccountMovementORM, source.id)) == source
        )
        assert transaction_mapper.to_domain(session.get(TransactionORM, original.id)) == original


def test_reversal_reference_and_nullable_idempotency(migrated_engine, records):
    original, _, _ = records
    sessions = create_session_factory(migrated_engine)
    sources = [
        replace(
            original, id=uuid4(), reversal_of_id=original.id, idempotency_key=None, description=None
        )
        for _ in range(2)
    ]
    with sessions.begin() as session:
        session.add_all([transaction_mapper.to_orm(source) for source in sources])
    with sessions() as session:
        for source in sources:
            assert transaction_mapper.to_domain(session.get(TransactionORM, source.id)) == source


def test_server_pending_default_and_all_nullable_movement_fields(migrated_engine, records):
    original, account, effect = records
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO banking.transactions "
                "(id, transaction_type, amount, currency, effective_at, created_at) "
                "VALUES (:id, 'DEPOSIT', 0.01, 'CZK', :at, :at)"
            ),
            {"id": uuid4(), "at": original.effective_at},
        )
        assert (
            connection.scalar(
                text("SELECT status FROM banking.transactions WHERE posted_at IS NULL")
            )
            == "PENDING"
        )
    source = replace(
        effect,
        id=uuid4(),
        balance_after=None,
        category=None,
        counterparty_account=None,
        counterparty_bank=None,
    )
    sessions = create_session_factory(migrated_engine)
    with sessions.begin() as session:
        session.add(account_movement_mapper.to_orm(source))
    with sessions() as session:
        assert (
            account_movement_mapper.to_domain(session.get(AccountMovementORM, source.id)) == source
        )


@pytest.mark.parametrize(
    ("table", "changes", "constraint"),
    [
        ("transactions", {"transaction_type": "INVALID"}, "ck_transactions_transaction_type"),
        ("transactions", {"status": "INVALID"}, "ck_transactions_status"),
        ("transactions", {"amount": Decimal("0")}, "ck_transactions_amount"),
        ("transactions", {"amount": Decimal("-1")}, "ck_transactions_amount"),
        ("transactions", {"amount": Decimal("NaN")}, "ck_transactions_amount"),
        ("transactions", {"posted_at": None}, "ck_transactions_posted_at"),
        ("transactions", {"status": "REVERSED", "posted_at": None}, "ck_transactions_posted_at"),
        ("transactions", {"status": "PENDING"}, "ck_transactions_posted_at"),
        ("transactions", {"status": "REJECTED"}, "ck_transactions_posted_at"),
        ("transactions", {"currency": "czk"}, "ck_transactions_currency"),
        ("transactions", {"reversal_of_id": uuid4()}, "fk_transactions_reversal_of_id"),
        ("account_movements", {"direction": "INVALID"}, "ck_account_movements_direction"),
        ("account_movements", {"amount": Decimal("0")}, "ck_account_movements_amount"),
        ("account_movements", {"amount": Decimal("-1")}, "ck_account_movements_amount"),
        ("account_movements", {"amount": Decimal("NaN")}, "ck_account_movements_amount"),
        (
            "account_movements",
            {"balance_after": Decimal("NaN")},
            "ck_account_movements_balance_after",
        ),
        ("account_movements", {"transaction_id": uuid4()}, "fk_account_movements_transaction_id"),
        ("account_movements", {"account_id": uuid4()}, "fk_account_movements_account_id"),
    ],
)
def test_constraints_are_enforced_by_postgresql(
    migrated_engine, records, table, changes, constraint
):
    original, _, effect = records
    reference = original.id if table == "transactions" else effect.id
    assignments = ", ".join(f"{field} = :{field}" for field in changes)
    with pytest.raises(IntegrityError) as error, migrated_engine.begin() as connection:
        connection.execute(
            text(f"UPDATE banking.{table} SET {assignments} WHERE id = :id"),
            {**changes, "id": reference},
        )
    assert error.value.orig.diag.constraint_name == constraint


def test_self_reversal_and_duplicate_key_are_rejected(migrated_engine, records):
    original, _, _ = records
    with pytest.raises(IntegrityError) as error, migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE banking.transactions SET reversal_of_id = id WHERE id = :id"),
            {"id": original.id},
        )
    assert error.value.orig.diag.constraint_name == "ck_transactions_reversal_of_id"
    sessions = create_session_factory(migrated_engine)
    with pytest.raises(IntegrityError) as error, sessions.begin() as session:
        session.add(transaction_mapper.to_orm(replace(original, id=uuid4())))
    assert error.value.orig.diag.constraint_name == "uq_transactions_idempotency_key"
    with sessions() as session:
        assert transaction_mapper.to_domain(session.get(TransactionORM, original.id)) == original


def test_foreign_keys_prevent_deleting_referenced_rows(migrated_engine, records):
    original, account, _ = records
    for table, reference in (("transactions", original.id), ("accounts", account.id)):
        with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM banking.{table} WHERE id = :id"), {"id": reference}
            )


def test_indexes_and_numeric_types(migrated_engine):
    inspector = inspect(migrated_engine)
    for table, columns in (
        ("transactions", ["amount"]),
        ("account_movements", ["amount", "balance_after"]),
    ):
        types = {
            column["name"]: column["type"]
            for column in inspector.get_columns(table, schema="banking")
        }
        for field in columns:
            assert types[field].precision == 18 and types[field].scale == 2
    tx_index = next(
        index
        for index in inspector.get_indexes("transactions", schema="banking")
        if index["name"] == "ix_banking_transactions_status_created_at"
    )
    assert tx_index["column_names"] == ["status", "created_at"]
    assert "desc" in tx_index["column_sorting"]["created_at"]
    movement_indexes = {
        index["name"]: index
        for index in inspector.get_indexes("account_movements", schema="banking")
    }
    ordered = movement_indexes["ix_banking_account_movements_account_booked_at_id"]
    assert ordered["column_names"] == ["account_id", "booked_at", "id"]
    assert "desc" in ordered["column_sorting"]["booked_at"]
    assert movement_indexes["ix_banking_account_movements_transaction_id"]["column_names"] == [
        "transaction_id"
    ]
