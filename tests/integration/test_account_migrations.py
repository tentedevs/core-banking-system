import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CHAR, Date, DateTime, Engine, String, Uuid, inspect, text
from sqlalchemy.exc import ProgrammingError

from infrastructure.persistence.database import create_database_engine
from infrastructure.persistence.migrate import alembic_config, initialize_database, verify_head
from infrastructure.persistence.models import Base
from infrastructure.settings import Settings

pytestmark = pytest.mark.integration


def test_schema_types_constraints_and_metadata(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    columns = {col["name"]: col for col in inspector.get_columns("accounts", schema="banking")}
    table = Base.metadata.tables["banking.accounts"]
    assert set(columns) == set(table.columns.keys())
    for column in table.columns:
        assert columns[column.name]["nullable"] == column.nullable
    for field in ("id", "customer_id"):
        assert isinstance(columns[field]["type"], Uuid)
    for field, length in (("account_number", 34), ("product_type", 30), ("status", 20)):
        assert isinstance(columns[field]["type"], String)
        assert columns[field]["type"].length == length
    assert isinstance(columns["currency"]["type"], CHAR)
    assert columns["currency"]["type"].length == 3
    for field in ("opened_at", "closed_at"):
        assert isinstance(columns[field]["type"], Date)
    for field in ("created_at", "updated_at"):
        assert isinstance(columns[field]["type"], DateTime)
        assert columns[field]["type"].timezone
    assert inspector.get_pk_constraint("accounts", schema="banking")["constrained_columns"] == [
        "id"
    ]
    assert inspector.get_foreign_keys("accounts", schema="banking") == []
    assert {
        check["name"] for check in inspector.get_check_constraints("accounts", schema="banking")
    } == {
        "ck_accounts_product_type",
        "ck_accounts_status",
        "ck_accounts_lifecycle_dates",
        "ck_accounts_closed_at",
        "ck_accounts_account_number",
        "ck_accounts_currency",
    }
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"include_schemas": True, "compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []
        verify_head(connection, alembic_config())


def test_upgrade_downgrade_preserves_unrelated_objects(
    isolated_database_settings: Settings,
) -> None:
    engine = create_database_engine(isolated_database_settings)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA banking"))
            connection.execute(text("CREATE TABLE banking.unrelated (value integer)"))
            connection.execute(text("INSERT INTO banking.unrelated VALUES (42)"))
            connection.execute(text("CREATE TABLE public.unrelated (value integer)"))
        initialize_database(engine)
        initialize_database(engine)
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert not inspect(connection).has_table("accounts", schema="banking")
            assert connection.scalar(text("SELECT value FROM banking.unrelated")) == 42
            assert inspect(connection).has_table("unrelated", schema="public")
            assert "banking" in inspect(connection).get_schema_names()
            command.upgrade(config, "head")
            verify_head(connection, config)
            assert inspect(connection).has_table("accounts", schema="banking")
    finally:
        engine.dispose()


def test_existing_accounts_are_not_overwritten(isolated_database_settings: Settings) -> None:
    engine = create_database_engine(isolated_database_settings)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA banking"))
            connection.execute(text("CREATE TABLE banking.accounts (product_type varchar(30))"))
            connection.execute(text("INSERT INTO banking.accounts VALUES ('CURRENT_ACCOUNT')"))
        with pytest.raises(ProgrammingError):
            initialize_database(engine)
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT product_type FROM banking.accounts"))
                == "CURRENT_ACCOUNT"
            )
    finally:
        engine.dispose()
