from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update

from application.account_messages import CreateAccountCommand
from application.transaction_messages import CreateDepositCommand, CreateTransferCommand
from application.use_cases.create_account import CreateAccount
from application.use_cases.create_deposit import CreateDeposit
from application.use_cases.create_transfer import CreateTransfer
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.models import AccountMovementORM
from infrastructure.persistence.repositories.risk_evidence import SQLAlchemyRiskEvidenceQuery

pytestmark = pytest.mark.integration


def test_evidence_filters_ownership_currency_and_window_and_has_consistent_pages(migrated_engine):
    sessions = create_session_factory(migrated_engine)

    def factory():
        return SQLAlchemyAccountUnitOfWork(sessions)

    customer = uuid4()
    a = CreateAccount(factory()).execute(CreateAccountCommand(customer, "CZK"))
    b = CreateAccount(factory()).execute(CreateAccountCommand(customer, "CZK"))
    other = CreateAccount(factory()).execute(CreateAccountCommand(uuid4(), "CZK"))
    euro = CreateAccount(factory()).execute(CreateAccountCommand(customer, "EUR"))
    for account in (a, other, euro):
        CreateDeposit(factory()).execute(
            CreateDepositCommand(account.id, Decimal("1000"), account.currency, str(uuid4()))
        )
    CreateTransfer(factory()).execute(
        CreateTransferCommand(a.id, b.id, Decimal("100"), "CZK", str(uuid4()))
    )
    now = datetime.now(UTC)
    with sessions() as session:
        query = SQLAlchemyRiskEvidenceQuery(session)
        first = query.page(customer, "CZK", now - timedelta(days=1), now + timedelta(days=1), 1, 0)
        remaining = query.page(
            customer, "CZK", now - timedelta(days=1), now + timedelta(days=1), 100, 1
        )
        assert first["reference"] == remaining["reference"]
        assert first["has_more"] is True and remaining["has_more"] is False
        items = first["items"] + remaining["items"]
        assert len(items) == 3
        assert {item["account_id"] for item in items} == {str(a.id), str(b.id)}
        assert sum(item["own_transfer"] for item in items) == 2
        empty = query.page(
            customer, "CZK", now - timedelta(days=10), now - timedelta(days=9), 100, 0
        )
        assert empty["items"] == []
    with sessions() as session, session.begin():
        session.execute(
            update(AccountMovementORM)
            .where(AccountMovementORM.account_id == a.id)
            .values(category="SALARY")
        )
    with sessions() as session:
        changed = SQLAlchemyRiskEvidenceQuery(session).page(
            customer, "CZK", now - timedelta(days=1), now + timedelta(days=1), 100, 0
        )
        assert changed["reference"] != first["reference"]
