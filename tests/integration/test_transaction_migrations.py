from dataclasses import asdict
from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from domain.account.entities import Account
from infrastructure.persistence.database import create_database_engine
from infrastructure.persistence.migrate import alembic_config, initialize_database, verify_head
from infrastructure.persistence.models import Base

pytestmark = pytest.mark.integration


def test_incremental_upgrade_downgrade_preserves_accounts(isolated_database_settings):
    engine = create_database_engine(isolated_database_settings)
    account = Account.create(
        customer_id=uuid4(),
        account_number="preserved-account",
        currency="CZK",
        opened_at=date(2024, 1, 1),
    )
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "0001_create_accounts")
            connection.execute(
                text(
                    "INSERT INTO banking.accounts "
                    "(id, customer_id, account_number, product_type, currency, status, opened_at, "
                    "closed_at, created_at, updated_at) VALUES "
                    "(:id, :customer_id, :account_number, :product_type, :currency, "
                    ":status, :opened_at, "
                    ":closed_at, :created_at, :updated_at)"
                ),
                asdict(account),
            )
            oid = connection.scalar(text("SELECT 'banking.accounts'::regclass::oid"))
            command.upgrade(config, "head")
            verify_head(connection, config)
            context = MigrationContext.configure(
                connection, opts={"include_schemas": True, "compare_server_default": True}
            )
            assert compare_metadata(context, Base.metadata) == []
            connection.execute(text("CREATE TABLE banking.unrelated (value integer)"))
            connection.execute(text("INSERT INTO banking.unrelated VALUES (42)"))
            transaction_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO banking.transactions "
                    "(id, transaction_type, amount, currency, effective_at, created_at) "
                    "VALUES (:id, 'DEPOSIT', 1.23, 'CZK', :at, :at)"
                ),
                {"id": transaction_id, "at": account.created_at},
            )
            connection.execute(
                text(
                    "INSERT INTO banking.account_movements "
                    "(id, transaction_id, account_id, direction, amount, booked_at) "
                    "VALUES (:id, :transaction_id, :account_id, 'CREDIT', 1.23, :at)"
                ),
                {
                    "id": uuid4(),
                    "transaction_id": transaction_id,
                    "account_id": account.id,
                    "at": account.created_at,
                },
            )
            command.downgrade(config, "0001_create_accounts")
            inspector = inspect(connection)
            assert not inspector.has_table("transactions", schema="banking")
            assert not inspector.has_table("account_movements", schema="banking")
            assert connection.scalar(text("SELECT 'banking.accounts'::regclass::oid")) == oid
            assert (
                connection.scalar(
                    text("SELECT account_number FROM banking.accounts WHERE id = :id"),
                    {"id": account.id},
                )
                == account.account_number
            )
            assert connection.scalar(text("SELECT value FROM banking.unrelated")) == 42
            command.upgrade(config, "head")
            verify_head(connection, config)
        initialize_database(engine)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM banking.accounts")) == 1
    finally:
        engine.dispose()
