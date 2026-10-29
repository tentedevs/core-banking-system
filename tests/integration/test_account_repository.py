from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from domain.account.entities import Account
from domain.account.enums import AccountStatus
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.repositories.account_repository import SQLAlchemyAccountRepository
from ports.account_repository import AccountRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(migrated_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(migrated_engine)


@pytest.fixture
def account() -> Account:
    return Account.create(
        customer_id=uuid4(),
        account_number="0000123456",
        currency="EUR",
        opened_at=date(2024, 1, 1),
    )


def test_save_and_read_every_field(sessions: sessionmaker[Session], account: Account) -> None:
    before = asdict(account)
    with sessions.begin() as session:
        repository: AccountRepository = SQLAlchemyAccountRepository(session)
        repository.save(account)
        assert repository.get_by_id(account.id) == account
        assert repository.get_by_account_number(account.account_number) == account
    with sessions() as session:
        repository = SQLAlchemyAccountRepository(session)
        assert repository.get_by_id(account.id) == account
        assert repository.get_by_account_number(account.account_number) == account
    assert asdict(account) == before


def test_unknown_accounts_and_empty_lists(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        repository = SQLAlchemyAccountRepository(session)
        assert repository.get_by_id(uuid4()) is None
        assert repository.get_by_account_number("unknown") is None
        assert repository.list_by_customer(uuid4()) == []
        assert repository.list_all() == []


def test_queries_filter_order_and_paginate(
    sessions: sessionmaker[Session], account: Account
) -> None:
    other_customer = uuid4()
    accounts = [
        replace(
            account,
            id=UUID(int=i),
            account_number=f"account-{i}",
            customer_id=other_customer if i == 2 else account.customer_id,
        )
        for i in range(1, 5)
    ]
    with sessions.begin() as session:
        repository = SQLAlchemyAccountRepository(session)
        for item in reversed(accounts):
            repository.save(item)
    with sessions() as session:
        repository = SQLAlchemyAccountRepository(session)
        for _ in range(2):
            assert repository.list_all() == accounts
            assert repository.list_all(limit=2, offset=1) == accounts[1:3]
            assert repository.list_all(limit=1, offset=3) == accounts[3:]
            assert repository.list_all(limit=100) == accounts
            assert repository.list_all(offset=4) == []
            expected = [accounts[0], accounts[2], accounts[3]]
            assert repository.list_by_customer(account.customer_id) == expected
            assert repository.list_by_customer(account.customer_id, limit=1, offset=1) == [
                accounts[2]
            ]
            assert repository.list_by_customer(account.customer_id, offset=3) == []
            assert repository.list_by_customer(other_customer) == [accounts[1]]
            assert repository.list_by_customer(uuid4()) == []


def test_default_page_is_bounded(sessions: sessionmaker[Session], account: Account) -> None:
    accounts = [
        replace(account, id=UUID(int=i), account_number=f"number-{i}") for i in range(1, 52)
    ]
    with sessions.begin() as session:
        repository = SQLAlchemyAccountRepository(session)
        for item in reversed(accounts):
            repository.save(item)
    with sessions() as session:
        repository = SQLAlchemyAccountRepository(session)
        assert repository.list_all() == accounts[:50]
        assert repository.list_by_customer(account.customer_id) == accounts[:50]
        assert repository.list_all(offset=50) == accounts[50:]
        assert repository.list_by_customer(account.customer_id, offset=50) == accounts[50:]


def test_status_updates_preserve_identity_and_execute_update(
    sessions: sessionmaker[Session], account: Account, migrated_engine: Engine
) -> None:
    with sessions.begin() as session:
        SQLAlchemyAccountRepository(session).save(account)
    statements: list[str] = []

    def record(connection, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(migrated_engine, "before_cursor_execute", record)
    try:
        blocked = account.block()
        active = blocked.reactivate()
        for changed in (blocked, active):
            with sessions.begin() as session:
                SQLAlchemyAccountRepository(session).save(changed)
            with sessions() as session:
                repository = SQLAlchemyAccountRepository(session)
                assert repository.get_by_id(account.id) == changed
                assert repository.get_by_account_number(account.account_number) == changed
                assert repository.list_all() == [changed]
    finally:
        event.remove(migrated_engine, "before_cursor_execute", record)
    assert statements.count("UPDATE") == 2
    assert "INSERT" not in statements and "DELETE" not in statements


def test_existing_original_attributes_are_preserved(
    sessions: sessionmaker[Session], account: Account
) -> None:
    with sessions.begin() as session:
        SQLAlchemyAccountRepository(session).save(account)
    altered = replace(
        account.block(),
        customer_id=uuid4(),
        account_number="different-number",
        currency="USD",
        opened_at=date(2023, 1, 1),
        created_at=datetime(2023, 1, 1, tzinfo=UTC),
    )
    with sessions.begin() as session:
        SQLAlchemyAccountRepository(session).save(altered)
    with sessions() as session:
        expected = replace(account, status=AccountStatus.BLOCKED, updated_at=altered.updated_at)
        assert SQLAlchemyAccountRepository(session).get_by_id(account.id) == expected


def test_repeated_save_in_same_transaction(
    sessions: sessionmaker[Session], account: Account
) -> None:
    blocked = account.block()
    with sessions.begin() as session:
        repository = SQLAlchemyAccountRepository(session)
        repository.save(account)
        repository.save(blocked)
        repository.save(blocked)
        assert repository.list_all() == [blocked]
    with sessions() as session:
        assert SQLAlchemyAccountRepository(session).list_all() == [blocked]


def test_closed_accounts_remain_queryable(
    sessions: sessionmaker[Session], account: Account
) -> None:
    historical = replace(account, status=AccountStatus.CLOSED, closed_at=date(2024, 2, 1))
    with sessions.begin() as session:
        SQLAlchemyAccountRepository(session).save(historical)
    with sessions() as session:
        repository = SQLAlchemyAccountRepository(session)
        assert repository.get_by_id(account.id) == historical
        assert repository.get_by_account_number(account.account_number) == historical
        assert repository.list_by_customer(account.customer_id) == [historical]
        assert repository.list_all() == [historical]


def test_saves_share_transaction_without_auto_commit(
    sessions: sessionmaker[Session], account: Account
) -> None:
    other = replace(account, id=uuid4(), account_number="other-number")
    with sessions() as session:
        repository = SQLAlchemyAccountRepository(session)
        repository.save(account)
        SQLAlchemyAccountRepository(session).save(other)
        session.flush()
        assert repository.get_by_id(account.id) == account
        assert len(repository.list_all()) == 2
        with sessions() as observer:
            assert SQLAlchemyAccountRepository(observer).list_all() == []
        session.commit()
    with sessions() as observer:
        assert set(item.id for item in SQLAlchemyAccountRepository(observer).list_all()) == {
            account.id,
            other.id,
        }


def test_uncommitted_writes_are_discarded_on_close(
    sessions: sessionmaker[Session], account: Account
) -> None:
    with sessions() as session:
        SQLAlchemyAccountRepository(session).save(account)
        session.flush()
    with sessions() as observer:
        assert SQLAlchemyAccountRepository(observer).get_by_id(account.id) is None


@pytest.mark.parametrize("failure", ["duplicate", "length", "check", "caller"])
def test_failed_transaction_leaves_no_partial_data(
    sessions: sessionmaker[Session], account: Account, failure: str
) -> None:
    error = {
        "duplicate": IntegrityError,
        "length": DataError,
        "check": IntegrityError,
        "caller": ValueError,
    }[failure]
    with pytest.raises(error), sessions.begin() as session:
        repository = SQLAlchemyAccountRepository(session)
        repository.save(account)
        session.flush()
        if failure == "caller":
            raise ValueError("Caller aborts the operation")
        if failure == "check":
            session.execute(
                text("UPDATE banking.accounts SET status = 'INVALID' WHERE id = :id"),
                {"id": account.id},
            )
        else:
            number = account.account_number if failure == "duplicate" else "x" * 35
            repository.save(replace(account, id=uuid4(), account_number=number))
            session.flush()
    with sessions() as observer:
        assert SQLAlchemyAccountRepository(observer).list_all() == []


def test_failed_update_is_rolled_back(sessions: sessionmaker[Session], account: Account) -> None:
    with sessions.begin() as session:
        SQLAlchemyAccountRepository(session).save(account)
    with pytest.raises(IntegrityError), sessions.begin() as session:
        repository = SQLAlchemyAccountRepository(session)
        repository.save(account.block())
        session.flush()
        repository.save(replace(account, id=uuid4()))
        session.flush()
    with sessions() as observer:
        assert SQLAlchemyAccountRepository(observer).list_all() == [account]


def test_repository_does_not_manage_session_lifecycle(
    sessions: sessionmaker[Session], account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Repository called commit, rollback, close or merge")

    with sessions.begin() as session:
        with monkeypatch.context() as patch:
            for method in ("commit", "rollback", "close", "merge"):
                patch.setattr(session, method, forbidden)
            repository = SQLAlchemyAccountRepository(session)
            repository.save(account)
            assert repository.get_by_id(account.id) == account
            assert repository.get_by_account_number(account.account_number) == account
            repository.save(account.block())
            assert repository.list_all()[0].status is AccountStatus.BLOCKED
            assert (
                repository.list_by_customer(account.customer_id)[0].status is AccountStatus.BLOCKED
            )


@pytest.mark.parametrize(
    "operation", ["save", "get_by_id", "get_by_account_number", "list_all", "list_by_customer"]
)
def test_unexpected_database_errors_propagate(
    sessions: sessionmaker[Session], account: Account, operation: str
) -> None:
    with sessions() as session:
        # Deterministic database error independent of server timings or sleeps.
        session.execute(text("DROP TABLE banking.accounts"))
        repository = SQLAlchemyAccountRepository(session)
        actions: dict[str, Callable[[], object]] = {
            "save": lambda: repository.save(account),
            "get_by_id": lambda: repository.get_by_id(account.id),
            "get_by_account_number": lambda: repository.get_by_account_number(
                account.account_number
            ),
            "list_all": repository.list_all,
            "list_by_customer": lambda: repository.list_by_customer(account.customer_id),
        }
        # Undefined table is a ProgrammingError, propagated without HTTP/domain wrapping.
        with pytest.raises(ProgrammingError):
            actions[operation]()
