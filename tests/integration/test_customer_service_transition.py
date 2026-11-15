from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select

from application.account_messages import CreateAccountCommand
from application.use_cases.create_account import CreateAccount
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.migrate import alembic_config
from infrastructure.persistence.models import CustomerAccountOpeningORM, CustomerOnboardingORM

pytestmark = pytest.mark.integration


def test_additive_migration_preserves_completed_account_opening(migrated_engine):
    sessions = create_session_factory(migrated_engine)
    customer, actor = uuid4(), uuid4()
    account = CreateAccount(SQLAlchemyAccountUnitOfWork(sessions)).execute(
        CreateAccountCommand(customer, "CZK"),
    )
    with migrated_engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "0006_create_customer_onboardings")
        connection.execute(
            CustomerOnboardingORM.__table__.insert().values(
                actor_id=actor,
                customer_id=customer,
                fingerprint="a" * 64,
                account_id=account.id,
            )
        )
        command.upgrade(config, "head")
        row = connection.execute(select(CustomerAccountOpeningORM.__table__)).one()
        assert row.customer_id == customer and row.account_id == account.id
        assert row.currency == "CZK"
        assert connection.execute(select(CustomerOnboardingORM.__table__)).one().actor_id == actor
