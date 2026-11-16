import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from application.account_balance_service import AccountBalanceService
from application.account_messages import BlockAccountCommand, CreateAccountCommand
from application.transaction_messages import (
    CreateDepositCommand,
    CreateTransferCommand,
    CreateWithdrawalCommand,
    GetAccountBalanceQuery,
    GetTransactionQuery,
    ListAccountMovementsQuery,
    ListTransactionsQuery,
)
from application.transaction_posting import AccountNotActive
from application.use_cases.block_account import BlockAccount
from application.use_cases.create_account import CreateAccount
from application.use_cases.create_deposit import CreateDeposit
from application.use_cases.create_transfer import CreateTransfer
from application.use_cases.create_withdrawal import CreateWithdrawal
from application.use_cases.get_account import AccountNotFound
from application.use_cases.get_account_balance import GetAccountBalance
from application.use_cases.get_transaction import GetTransaction, TransactionNotFound
from application.use_cases.list_account_movements import ListAccountMovements
from application.use_cases.list_transactions import ListTransactions
from domain.account.enums import AccountStatus
from domain.account_balance.exceptions import InsufficientFunds
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.mappers import transaction_mapper
from infrastructure.persistence.migrate import alembic_config
from infrastructure.persistence.models import Base
from infrastructure.persistence.repositories.account_movement_repository import (
    SQLAlchemyAccountMovementRepository,
)
from infrastructure.persistence.repositories.balance_repository import SQLAlchemyBalanceRepository
from infrastructure.persistence.repositories.transaction_repository import (
    SQLAlchemyTransactionRepository,
)
from ports.balance_repository import BalanceCurrencyMismatch, BalanceNotFound
from ports.transaction_repository import IdempotencyConflict, TransactionPersistenceConflict
from tests.transaction_factories import transaction

pytestmark = pytest.mark.integration


@pytest.fixture
def factory(migrated_engine):
    sessions = create_session_factory(migrated_engine)
    return lambda: SQLAlchemyAccountUnitOfWork(sessions)


@pytest.fixture
def accounts(factory):
    return [CreateAccount(factory()).execute(CreateAccountCommand(uuid4())) for _ in range(2)]


def fund(factory, account, amount="100", key=None):
    return CreateDeposit(factory()).execute(
        CreateDepositCommand(account.id, Decimal(amount), account.currency, key or str(uuid4()))
    )


def balance(factory, account):
    return GetAccountBalance(factory()).execute(GetAccountBalanceQuery(account.id))


def history(factory, account):
    return ListAccountMovements(factory()).execute(ListAccountMovementsQuery(account.id))


def counts(engine):
    with engine.connect() as connection:
        return tuple(
            connection.scalar(text(f"SELECT count(*) FROM banking.{table}"))
            for table in ("transactions", "account_movements", "transaction_requests")
        )


def wait_for_locks(engine, count=1):
    deadline = time.monotonic() + 8
    with engine.connect() as connection:
        while time.monotonic() < deadline:
            waiting = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            if waiting >= count:
                return
            time.sleep(0.01)
    pytest.fail("Concurrent operation did not wait for the PostgreSQL lock")


def reconcile(factory, accounts):
    with factory() as work:
        service = AccountBalanceService(work.accounts, work.balances)
        for account in accounts:
            assert service.check_consistency(account.id, currency=account.currency).is_consistent


def test_money_operations_relationships_balances_and_reconciliation(
    factory, accounts, migrated_engine
):
    a, b = accounts
    deposited = fund(factory, a)
    withdrawn = CreateWithdrawal(factory()).execute(
        CreateWithdrawalCommand(a.id, Decimal("20.25"), "CZK", "withdraw", "cash")
    )
    transferred = CreateTransfer(factory()).execute(
        CreateTransferCommand(a.id, b.id, Decimal("30.10"), "CZK", "transfer", "internal")
    )
    assert (
        balance(factory, a).booked_balance
        == balance(factory, a).available_balance
        == Decimal("49.65")
    )
    assert balance(factory, b).available_balance == Decimal("30.10")
    assert counts(migrated_engine) == (3, 4, 3)
    effects = history(factory, a)
    expected = {
        deposited.id: (MovementDirection.CREDIT, Decimal("100")),
        withdrawn.id: (MovementDirection.DEBIT, Decimal("79.75")),
        transferred.id: (MovementDirection.DEBIT, Decimal("49.65")),
    }
    for effect in effects:
        assert (effect.direction, effect.balance_after) == expected[effect.transaction_id]
        tx = GetTransaction(factory()).execute(GetTransactionQuery(effect.transaction_id))
        assert tx.status is TransactionStatus.POSTED and tx.posted_at == effect.booked_at
        assert tx.amount == effect.amount and tx.currency == "CZK"
    credit = history(factory, b)[0]
    assert credit.transaction_id == transferred.id and credit.direction is MovementDirection.CREDIT
    assert (
        credit.balance_after == Decimal("30.10") and credit.counterparty_account == a.account_number
    )
    assert (
        next(m for m in effects if m.transaction_id == deposited.id).category
        == "SIMULATED_CASH_DEPOSIT"
    )
    assert next(m for m in effects if m.transaction_id == deposited.id).counterparty_account is None
    reconcile(factory, accounts)


@pytest.mark.parametrize("kind", ["deposit", "withdrawal", "transfer"])
def test_retry_returns_original_and_does_not_repeat_money(factory, accounts, migrated_engine, kind):
    a, b = accounts
    fund(factory, a)
    use_case, request = {
        "deposit": (CreateDeposit, CreateDepositCommand(a.id, Decimal("10"), "CZK", "once")),
        "withdrawal": (
            CreateWithdrawal,
            CreateWithdrawalCommand(a.id, Decimal("10"), "CZK", "once"),
        ),
        "transfer": (
            CreateTransfer,
            CreateTransferCommand(a.id, b.id, Decimal("10"), "CZK", "once"),
        ),
    }[kind]
    original = use_case(factory()).execute(request)
    before = [balance(factory, account) for account in accounts]
    before_counts = counts(migrated_engine)
    # A fresh Unit of Work simulates a different process retrying after response loss.
    assert use_case(factory()).execute(replace(request, amount=Decimal("10.0000"))) == original
    assert [balance(factory, account) for account in accounts] == before
    assert counts(migrated_engine) == before_counts
    reconcile(factory, accounts)


@pytest.mark.parametrize("change", ["amount", "description", "currency", "account", "operation"])
def test_key_conflicts_cover_entire_request(factory, accounts, migrated_engine, change):
    a, b = accounts
    request = CreateDepositCommand(a.id, Decimal("10"), "CZK", "same")
    original = CreateDeposit(factory()).execute(request)
    changed = {
        "amount": replace(request, amount=Decimal("11")),
        "description": replace(request, description="different"),
        "currency": replace(request, currency="EUR"),
        "account": replace(request, account_id=b.id),
        "operation": CreateWithdrawalCommand(a.id, Decimal("10"), "CZK", "same"),
    }[change]
    use_case = CreateWithdrawal if change == "operation" else CreateDeposit
    with pytest.raises(IdempotencyConflict):
        use_case(factory()).execute(changed)
    assert counts(migrated_engine) == (1, 1, 1)
    assert GetTransaction(factory()).execute(GetTransactionQuery(original.id)) == original
    assert balance(factory, a).booked_balance == 10 and balance(factory, b).booked_balance == 0


@pytest.mark.parametrize("which", ["source", "destination"])
def test_transfer_requires_both_accounts_active(factory, accounts, migrated_engine, which):
    a, b = accounts
    fund(factory, a)
    blocked = a if which == "source" else b
    BlockAccount(factory()).execute(BlockAccountCommand(blocked.id))
    with pytest.raises(AccountNotActive):
        CreateTransfer(factory()).execute(
            CreateTransferCommand(a.id, b.id, Decimal("10"), "CZK", "blocked")
        )
    assert balance(factory, a).booked_balance == 100 and balance(factory, b).booked_balance == 0
    assert counts(migrated_engine) == (1, 1, 1)


def test_controlled_failures_and_retry_after_insufficient_funds(factory, accounts, migrated_engine):
    a, b = accounts
    request = CreateWithdrawalCommand(a.id, Decimal("10"), "CZK", "retry-after-failure")
    with pytest.raises(InsufficientFunds):
        CreateWithdrawal(factory()).execute(request)
    with pytest.raises(AccountNotFound):
        CreateDeposit(factory()).execute(
            CreateDepositCommand(uuid4(), Decimal("1"), "CZK", "missing")
        )
    with pytest.raises(BalanceCurrencyMismatch):
        CreateDeposit(factory()).execute(
            CreateDepositCommand(a.id, Decimal("1"), "EUR", "currency")
        )
    other = CreateAccount(factory()).execute(CreateAccountCommand(uuid4(), "EUR"))
    with pytest.raises(BalanceCurrencyMismatch):
        CreateTransfer(factory()).execute(
            CreateTransferCommand(a.id, other.id, Decimal("1"), "CZK", "cross-currency")
        )
    assert counts(migrated_engine) == (0, 0, 0)
    fund(factory, a)
    assert CreateWithdrawal(factory()).execute(request).status is TransactionStatus.POSTED
    assert balance(factory, a).available_balance == 90
    reconcile(factory, accounts)


@pytest.mark.parametrize("stage", ["debit", "first_movement", "post", "receipt", "commit"])
def test_database_failure_rolls_back_every_financial_effect(
    factory, accounts, migrated_engine, stage
):
    a, b = accounts
    fund(factory, a)
    before = [balance(factory, account) for account in accounts]
    cls, name = {
        "debit": (SQLAlchemyBalanceRepository, "persist_updated_balance"),
        "first_movement": (SQLAlchemyAccountMovementRepository, "add"),
        "post": (SQLAlchemyTransactionRepository, "post"),
        "receipt": (SQLAlchemyTransactionRepository, "record_request"),
        "commit": (SQLAlchemyAccountUnitOfWork, "commit"),
    }[stage]
    original = getattr(cls, name)

    def fail(self, *args, **kwargs):
        if stage != "commit":
            original(self, *args, **kwargs)
        # Independent sessions observe only the previous committed state.
        assert [balance(factory, account) for account in accounts] == before
        assert counts(migrated_engine) == (1, 1, 1)
        raise RuntimeError("database failure")

    with patch.object(cls, name, fail), pytest.raises(RuntimeError, match="database failure"):
        CreateTransfer(factory()).execute(
            CreateTransferCommand(a.id, b.id, Decimal("10"), "CZK", "rollback")
        )
    assert [balance(factory, account) for account in accounts] == before
    assert counts(migrated_engine) == (1, 1, 1)
    # No orphaned key reservation survives rollback.
    CreateTransfer(factory()).execute(
        CreateTransferCommand(a.id, b.id, Decimal("10"), "CZK", "rollback")
    )
    reconcile(factory, accounts)


@pytest.mark.parametrize("kind", ["withdrawals", "transfers"])
def test_concurrent_spending_cannot_overdraw(factory, accounts, migrated_engine, kind):
    a, b = accounts
    fund(factory, a)
    gate = Barrier(2)

    def spend(key):
        gate.wait(timeout=5)
        try:
            if kind == "withdrawals":
                return CreateWithdrawal(factory()).execute(
                    CreateWithdrawalCommand(a.id, Decimal("80"), "CZK", key)
                )
            return CreateTransfer(factory()).execute(
                CreateTransferCommand(a.id, b.id, Decimal("80"), "CZK", key)
            )
        except InsufficientFunds as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        with factory() as held:
            # Queue both operations at the account row lock before releasing them.
            held.accounts.get_by_id_for_update(
                min(accounts, key=lambda item: item.id).id if kind == "transfers" else a.id
            )
            futures = [pool.submit(spend, str(i)) for i in range(2)]
            try:
                wait_for_locks(migrated_engine, 2)
            finally:
                held.commit()
        results = [future.result(timeout=10) for future in futures]
    assert sum(isinstance(result, InsufficientFunds) for result in results) == 1
    assert balance(factory, a).available_balance == 20
    assert balance(factory, b).available_balance == (80 if kind == "transfers" else 0)
    assert counts(migrated_engine) == (2, 3 if kind == "transfers" else 2, 2)
    reconcile(factory, accounts)


def test_opposite_transfers_use_same_lock_order_without_deadlock(
    factory, accounts, migrated_engine
):
    a, b = accounts
    fund(factory, a)
    fund(factory, b)
    gate = Barrier(2)

    def transfer(source, destination, amount, key):
        gate.wait(timeout=5)
        return CreateTransfer(factory()).execute(
            CreateTransferCommand(source.id, destination.id, Decimal(amount), "CZK", key)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        with factory() as held:
            held.accounts.get_by_id_for_update(min(accounts, key=lambda item: item.id).id)
            futures = [
                pool.submit(transfer, a, b, "80", "ab"),
                pool.submit(transfer, b, a, "60", "ba"),
            ]
            try:
                wait_for_locks(migrated_engine, 2)
            finally:
                held.commit()
        assert all(
            future.result(timeout=10).status is TransactionStatus.POSTED for future in futures
        )
    assert balance(factory, a).booked_balance == 80
    assert balance(factory, b).booked_balance == 120
    assert counts(migrated_engine) == (4, 6, 4)
    reconcile(factory, accounts)


@pytest.mark.parametrize("conflict", [False, True])
def test_simultaneous_idempotency_keys_serialize_before_financial_writes(
    factory, accounts, migrated_engine, conflict
):
    a, b = accounts
    receipt_written, release = Event(), Event()
    original = SQLAlchemyTransactionRepository.record_request

    def hold(self, key, record):
        original(self, key, record)
        receipt_written.set()
        assert release.wait(timeout=10)

    first_command = CreateDepositCommand(a.id, Decimal("10"), "CZK", "concurrent-key")
    second_command = replace(first_command, account_id=b.id) if conflict else first_command
    with ThreadPoolExecutor(max_workers=2) as pool:
        with patch.object(SQLAlchemyTransactionRepository, "record_request", hold):
            first = pool.submit(CreateDeposit(factory()).execute, first_command)
            try:
                assert receipt_written.wait(timeout=5)
                second = pool.submit(CreateDeposit(factory()).execute, second_command)
                wait_for_locks(migrated_engine)
                assert not second.done()
            finally:
                release.set()
            result = first.result(timeout=10)
            if conflict:
                with pytest.raises(IdempotencyConflict):
                    second.result(timeout=10)
            else:
                assert second.result(timeout=10) == result
    assert counts(migrated_engine) == (1, 1, 1)
    assert balance(factory, a).booked_balance == 10 and balance(factory, b).booked_balance == 0
    reconcile(factory, accounts)


def test_concurrent_block_commits_before_waiting_deposit(factory, accounts, migrated_engine):
    a = accounts[0]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with factory() as held:
            current = held.accounts.get_by_id_for_update(a.id)
            held.accounts.save(current.block())
            held.accounts.session.flush()
            future = pool.submit(fund, factory, a)
            try:
                wait_for_locks(migrated_engine)
            finally:
                held.commit()
        with pytest.raises(AccountNotActive):
            future.result(timeout=10)
    assert balance(factory, a).booked_balance == 0
    assert counts(migrated_engine) == (0, 0, 0)


def test_posting_finishes_before_concurrent_block(factory, accounts, migrated_engine):
    a = accounts[0]
    posted, release = Event(), Event()
    original = SQLAlchemyTransactionRepository.record_request

    def hold(self, key, record):
        original(self, key, record)
        posted.set()
        assert release.wait(timeout=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        with patch.object(SQLAlchemyTransactionRepository, "record_request", hold):
            money = pool.submit(fund, factory, a, "10")
            try:
                assert posted.wait(timeout=5)
                blocking = pool.submit(BlockAccount(factory()).execute, BlockAccountCommand(a.id))
                wait_for_locks(migrated_engine)
                assert not blocking.done()
            finally:
                release.set()
            assert money.result(timeout=10).status is TransactionStatus.POSTED
            assert blocking.result(timeout=10).status is AccountStatus.BLOCKED
    assert balance(factory, a).available_balance == 10
    with pytest.raises(AccountNotActive):
        fund(factory, a, "1")
    assert counts(migrated_engine) == (1, 1, 1)
    reconcile(factory, [a])


def test_read_use_cases_pagination_ties_filters_and_missing(factory, accounts, migrated_engine):
    a, b = accounts
    first = fund(factory, a, "10")
    second = fund(factory, a, "20")
    third = CreateWithdrawal(factory()).execute(
        CreateWithdrawalCommand(a.id, Decimal("1"), "CZK", "withdraw")
    )
    # Force ties to verify UUID tie-breaks rather than incidental row order.
    with migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE banking.transactions SET created_at = :at"), {"at": first.created_at}
        )
        connection.execute(
            text("UPDATE banking.account_movements SET booked_at = :at"), {"at": first.posted_at}
        )
    items = ListTransactions(factory()).execute(ListTransactionsQuery())
    assert [item.id for item in items] == sorted([first.id, second.id, third.id])
    assert (
        ListTransactions(factory()).execute(ListTransactionsQuery(limit=1, offset=1)) == items[1:2]
    )
    assert (
        len(
            ListTransactions(factory()).execute(
                ListTransactionsQuery(
                    transaction_type=TransactionType.DEPOSIT, status=TransactionStatus.POSTED
                )
            )
        )
        == 2
    )
    assert (
        ListTransactions(factory()).execute(ListTransactionsQuery(status=TransactionStatus.PENDING))
        == []
    )
    assert ListTransactions(factory()).execute(ListTransactionsQuery(offset=100)) == []
    movements = history(factory, a)
    assert [item.id for item in movements] == sorted(item.id for item in movements)
    assert (
        ListAccountMovements(factory()).execute(ListAccountMovementsQuery(a.id, limit=1, offset=1))
        == movements[1:2]
    )
    assert history(factory, b) == []
    with pytest.raises(TransactionNotFound):
        GetTransaction(factory()).execute(GetTransactionQuery(uuid4()))
    with pytest.raises(AccountNotFound):
        ListAccountMovements(factory()).execute(ListAccountMovementsQuery(uuid4()))
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM banking.account_balance_openings WHERE account_id = :id"),
            {"id": b.id},
        )
        connection.execute(
            text("DELETE FROM banking.account_balances WHERE account_id = :id"), {"id": b.id}
        )
    with pytest.raises(BalanceNotFound):
        GetAccountBalance(factory()).execute(GetAccountBalanceQuery(b.id))
    with pytest.raises(BalanceNotFound):
        fund(factory, b)


def test_repositories_share_session_and_never_commit(factory, accounts, migrated_engine):
    a = accounts[0]
    pending = replace(transaction(), status=TransactionStatus.PENDING, posted_at=None)
    with factory() as work:
        session = work.accounts.session
        assert (
            work.balances.session is work.transactions.session is work.movements.session is session
        )
        with patch.object(session, "commit", side_effect=AssertionError("repository commit")):
            work.transactions.add(pending)
            assert work.transactions.get_by_id(pending.id) == pending
            assert work.transactions.get_by_idempotency_key(pending.idempotency_key) == pending
            assert work.transactions.get_by_id(uuid4()) is None
            assert work.transactions.get_by_idempotency_key("unknown") is None
            assert work.transactions.get_request("missing") is None
            assert len(work.transactions.list_all()) == 1
            assert work.movements.list_by_account(a.id) == []
            assert counts(migrated_engine) == (0, 0, 0)
    assert counts(migrated_engine) == (0, 0, 0)


def test_cannot_rewrite_posted_transaction(factory, accounts):
    original = fund(factory, accounts[0])
    with factory() as work:
        with pytest.raises(TransactionPersistenceConflict):
            work.transactions.post(replace(original, amount=Decimal("1")))
    assert GetTransaction(factory()).execute(GetTransactionQuery(original.id)) == original


def test_historical_key_without_fingerprint_is_never_reexecuted(factory, accounts, migrated_engine):
    existing = replace(transaction(), idempotency_key="legacy-key")
    with migrated_engine.begin() as connection:
        row = transaction_mapper.to_orm(existing)
        connection.execute(
            row.__table__.insert().values(
                **{column.key: getattr(row, column.key) for column in row.__table__.columns}
            )
        )
    with pytest.raises(IdempotencyConflict, match="fingerprint"):
        fund(factory, accounts[0], key="legacy-key")
    assert counts(migrated_engine) == (1, 0, 0)
    assert balance(factory, accounts[0]).booked_balance == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE banking.transaction_requests SET fingerprint = 'bad'",
        "UPDATE banking.transaction_requests SET idempotency_key = ' '",
        "UPDATE banking.transaction_requests "
        "SET transaction_id = '00000000-0000-0000-0000-000000000000'",
        "INSERT INTO banking.transaction_requests SELECT * FROM banking.transaction_requests",
    ],
)
def test_receipt_constraints(factory, accounts, migrated_engine, statement):
    fund(factory, accounts[0])
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(text(statement))
    assert counts(migrated_engine) == (1, 1, 1)


def test_incremental_receipt_migration_downgrade_preserves_financial_history(
    factory, accounts, migrated_engine
):
    original = fund(factory, accounts[0], key="migration-key")
    with migrated_engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "0003_create_account_balances")
        assert not inspect(connection).has_table("transaction_requests", schema="banking")
        assert connection.scalar(text("SELECT count(*) FROM banking.transactions")) == 1
        assert connection.scalar(text("SELECT count(*) FROM banking.account_movements")) == 1
        command.upgrade(config, "head")
        assert (
            compare_metadata(
                MigrationContext.configure(connection, opts={"include_schemas": True}),
                Base.metadata,
            )
            == []
        )
    assert GetTransaction(factory()).execute(GetTransactionQuery(original.id)) == original
    with pytest.raises(IdempotencyConflict):
        fund(factory, accounts[0], key="migration-key")
    assert balance(factory, accounts[0]).booked_balance == 100


def test_real_database_check_failure_discards_prior_balance_writes(
    factory, accounts, migrated_engine
):
    a, b = accounts
    fund(factory, a)
    original = SQLAlchemyAccountMovementRepository.add

    def break_foreign_key(self, effect):
        original(self, replace(effect, account_id=uuid4()))

    with patch.object(SQLAlchemyAccountMovementRepository, "add", break_foreign_key):
        with pytest.raises(IntegrityError):
            CreateTransfer(factory()).execute(
                CreateTransferCommand(a.id, b.id, Decimal("10"), "CZK", "fk-failure")
            )
    assert counts(migrated_engine) == (1, 1, 1)
    assert balance(factory, a).booked_balance == 100
    assert balance(factory, b).booked_balance == 0
    reconcile(factory, accounts)


def test_unique_key_violation_is_translated_at_uow_boundary(factory, accounts, migrated_engine):
    existing = fund(factory, accounts[0], key="existing")
    with pytest.raises(IdempotencyConflict), factory() as work:
        work.transactions.add(replace(existing, id=uuid4()))
    assert counts(migrated_engine) == (1, 1, 1)
    assert balance(factory, accounts[0]).booked_balance == 100


def test_retry_after_block_returns_the_committed_original(factory, accounts, migrated_engine):
    account = accounts[0]
    original = fund(factory, account, key="before-block")
    BlockAccount(factory()).execute(BlockAccountCommand(account.id))
    assert fund(factory, account, key="before-block") == original
    assert counts(migrated_engine) == (1, 1, 1)
    with pytest.raises(AccountNotActive):
        fund(factory, account, key="after-block")


@pytest.mark.parametrize("amount", ["0", "-1", ".001"])
def test_invalid_amounts_fail_before_any_database_writes(
    factory, accounts, migrated_engine, amount
):
    a, b = accounts
    for command_type, args in (
        (CreateDepositCommand, (a.id,)),
        (CreateWithdrawalCommand, (a.id,)),
        (CreateTransferCommand, (a.id, b.id)),
    ):
        with pytest.raises(ValueError):
            command_type(*args, Decimal(amount), "CZK", "invalid")
    assert counts(migrated_engine) == (0, 0, 0)
    assert balance(factory, a).booked_balance == balance(factory, b).booked_balance == 0
