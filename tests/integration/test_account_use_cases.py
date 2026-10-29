import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from application.use_cases.get_account import AccountNotFound, GetAccount
from application.use_cases.get_account_by_number import GetAccountByNumber
from application.use_cases.list_accounts import ListAccounts
from application.use_cases.reactivate_account import ReactivateAccount
from domain.account.enums import AccountStatus
from domain.account.exceptions import InvalidAccountStateTransition
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.models import AccountORM
from ports.account_repository import AccountNumberConflict
from tests.account_fakes import FixedAccountNumberGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
def work(migrated_engine: Engine):
    return SQLAlchemyAccountUnitOfWork(create_session_factory(migrated_engine))


def test_create_get_list_and_state_lifecycle(work, migrated_engine):
    account = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    assert account.currency == "CZK"
    assert account.product_type.value == "SAVINGS_ACCOUNT"
    assert account.status is AccountStatus.ACTIVE
    assert GetAccount(work).execute(GetAccountQuery(account.id)) == account
    assert (
        GetAccountByNumber(work).execute(GetAccountByNumberQuery(account.account_number)) == account
    )
    blocked = BlockAccount(work).execute(BlockAccountCommand(account.id))
    assert blocked.status is AccountStatus.BLOCKED
    assert GetAccount(work).execute(GetAccountQuery(account.id)) == blocked
    active = ReactivateAccount(work).execute(ReactivateAccountCommand(account.id))
    assert active.status is AccountStatus.ACTIVE
    assert GetAccount(work).execute(GetAccountQuery(account.id)) == active
    assert ListAccounts(work).execute(ListAccountsQuery()) == [active]
    assert ListAccounts(work).execute(ListAccountsQuery(account.customer_id)) == [active]
    assert migrated_engine.pool.checkedout() == 0


def test_filtering_and_pagination_execute_in_database(work):
    customer = uuid4()
    accounts = [CreateAccount(work).execute(CreateAccountCommand(customer)) for _ in range(3)]
    unrelated = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    expected = sorted(accounts, key=lambda account: account.id)
    assert (
        ListAccounts(work).execute(ListAccountsQuery(customer, limit=1, offset=1)) == expected[1:2]
    )
    assert ListAccounts(work).execute(ListAccountsQuery(customer)) == expected
    assert ListAccounts(work).execute(ListAccountsQuery()) == sorted(
        accounts + [unrelated], key=lambda account: account.id
    )
    assert ListAccounts(work).execute(ListAccountsQuery(uuid4())) == []


def test_reads_never_commit(work, migrated_engine):
    account = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    commits = []

    def committed(session):
        commits.append(True)

    event.listen(Session, "after_commit", committed)
    try:
        GetAccount(work).execute(GetAccountQuery(account.id))
        GetAccountByNumber(work).execute(GetAccountByNumberQuery(account.account_number))
        ListAccounts(work).execute(ListAccountsQuery())
        with pytest.raises(AccountNotFound):
            GetAccount(work).execute(GetAccountQuery(uuid4()))
        assert commits == []
    finally:
        event.remove(Session, "after_commit", committed)
    assert migrated_engine.pool.checkedout() == 0


def test_number_collision_is_typed_not_retried_and_session_released(work, migrated_engine):
    generator = FixedAccountNumberGenerator("same-number")
    create = CreateAccount(work, generator)
    original = create.execute(CreateAccountCommand(uuid4()))
    with pytest.raises(AccountNumberConflict, match="already in use"):
        create.execute(CreateAccountCommand(uuid4()))
    assert generator.calls == 2
    assert ListAccounts(work).execute(ListAccountsQuery()) == [original]
    assert migrated_engine.pool.checkedout() == 0
    # A failed transaction does not poison reuse of the transaction adapter.
    CreateAccount(work).execute(CreateAccountCommand(uuid4()))


@pytest.mark.parametrize("failure", ["caller", "duplicate", "check"])
def test_multiple_operations_roll_back_together(work, migrated_engine, failure):
    baseline = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    expected_error = {
        "caller": RuntimeError,
        "duplicate": AccountNumberConflict,
        "check": IntegrityError,
    }[failure]
    with pytest.raises(expected_error):
        with work as transaction:
            transaction.accounts.save(baseline.block())
            other = replace(baseline, id=uuid4(), account_number="another-number")
            transaction.accounts.save(other)
            if failure == "caller":
                raise RuntimeError("Abort before commit")
            if failure == "duplicate":
                transaction.accounts.save(replace(baseline, id=uuid4()))
            else:
                transaction.accounts.session.execute(
                    text("UPDATE banking.accounts SET currency = 'eur' WHERE id = :id"),
                    {"id": baseline.id},
                )
            transaction.commit()
    assert ListAccounts(work).execute(ListAccountsQuery()) == [baseline]
    assert migrated_engine.pool.checkedout() == 0


def test_no_explicit_commit_discards_writes(work):
    baseline = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    with work as transaction:
        transaction.accounts.save(baseline.block())
        transaction.accounts.session.flush()
    assert GetAccount(work).execute(GetAccountQuery(baseline.id)) == baseline


def test_invalid_and_missing_state_operations_release_sessions(work, migrated_engine):
    account = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    with pytest.raises(InvalidAccountStateTransition):
        ReactivateAccount(work).execute(ReactivateAccountCommand(account.id))
    with work as transaction:
        transaction.accounts.save(
            replace(account, status=AccountStatus.CLOSED, closed_at=account.opened_at)
        )
        transaction.commit()
    with pytest.raises(InvalidAccountStateTransition):
        ReactivateAccount(work).execute(ReactivateAccountCommand(account.id))
    with pytest.raises(AccountNotFound):
        BlockAccount(work).execute(BlockAccountCommand(uuid4()))
    with pytest.raises(AccountNotFound):
        GetAccountByNumber(work).execute(GetAccountByNumberQuery("unknown"))
    assert migrated_engine.pool.checkedout() == 0


def test_locked_read_refreshes_session_identity_map(work):
    account = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    with work as transaction:
        # Retain a stale ORM identity in this session before another transaction commits.
        stale = transaction.accounts.session.get(AccountORM, account.id)
        assert stale.status is AccountStatus.ACTIVE
        other_work = SQLAlchemyAccountUnitOfWork(work.sessions)
        blocked = BlockAccount(other_work).execute(BlockAccountCommand(account.id))
        assert stale.status is AccountStatus.ACTIVE
        assert transaction.accounts.get_by_id_for_update(account.id) == blocked
        assert stale.status is AccountStatus.BLOCKED


@pytest.mark.parametrize("operation", ["block", "reactivate"])
def test_concurrent_state_changes_observe_intervening_commit(work, migrated_engine, operation):
    account = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    if operation == "reactivate":
        account = BlockAccount(work).execute(BlockAccountCommand(account.id))

    def competing_operation():
        contender = SQLAlchemyAccountUnitOfWork(work.sessions)
        if operation == "block":
            return BlockAccount(contender).execute(BlockAccountCommand(account.id))
        return ReactivateAccount(contender).execute(ReactivateAccountCommand(account.id))

    with ThreadPoolExecutor(max_workers=1) as executor:
        with work as holder:
            locked = holder.accounts.get_by_id_for_update(account.id)
            future = executor.submit(competing_operation)
            # Observe a real PostgreSQL lock wait, rather than assuming a thread ran.
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                with migrated_engine.connect() as observer:
                    waiting = observer.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                            "AND query LIKE '%banking.accounts%' AND pid <> pg_backend_pid())"
                        )
                    )
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting, "Competing transaction did not wait on the account row"
            assert not future.done()
            changed = locked.block() if operation == "block" else locked.reactivate()
            holder.accounts.save(changed)
            holder.commit()
        # The waiting use case must revalidate the state committed by the winner.
        with pytest.raises(InvalidAccountStateTransition):
            future.result(timeout=5)
    assert GetAccount(work).execute(GetAccountQuery(account.id)) == changed
    assert migrated_engine.pool.checkedout() == 0


def test_unit_of_work_requires_context_and_rejects_nested_entry(work):
    with pytest.raises(RuntimeError, match="entered"):
        work.commit()
    with pytest.raises(RuntimeError, match="entered"):
        _ = work.accounts
    with work:
        with pytest.raises(RuntimeError, match="already active"):
            with work:
                pytest.fail("Nested transaction should be rejected")
    with pytest.raises(RuntimeError, match="entered"):
        _ = work.accounts
