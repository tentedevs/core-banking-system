import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from application.account_balance_service import AccountBalanceService
from application.account_messages import CreateAccountCommand
from application.use_cases.create_account import CreateAccount
from application.use_cases.get_account import AccountNotFound
from domain.account_balance.enums import BalanceInitializationPolicy
from domain.account_balance.exceptions import InsufficientFunds, InvalidAccountBalanceData
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_database_engine, create_session_factory
from infrastructure.persistence.mappers import account_movement_mapper, transaction_mapper
from infrastructure.persistence.migrate import alembic_config, verify_head
from infrastructure.persistence.models import AccountBalanceORM, Base
from infrastructure.persistence.repositories.balance_repository import SQLAlchemyBalanceRepository
from ports.balance_repository import (
    BalanceAlreadyInitialized,
    BalanceCurrencyMismatch,
    BalanceInitializationRequiresReplay,
    BalanceLockRequired,
    BalanceNotFound,
    BalanceOpeningNotFound,
)
from tests.transaction_factories import movement, transaction

pytestmark = pytest.mark.integration


@pytest.fixture
def work(migrated_engine):
    return SQLAlchemyAccountUnitOfWork(create_session_factory(migrated_engine))


@pytest.fixture
def account(work):
    return CreateAccount(work).execute(CreateAccountCommand(uuid4()))


def service(work):
    return AccountBalanceService(work.accounts, work.balances)


def read(work, account_id):
    with work:
        return work.balances.get_by_account_id(account_id)


def add_movement(work, account, amount, direction, status=TransactionStatus.POSTED, currency="CZK"):
    source = transaction()
    source = replace(
        source,
        idempotency_key=None,
        currency=currency,
        amount=amount,
        transaction_type=TransactionType.DEPOSIT,
        status=status,
        posted_at=source.posted_at
        if status in (TransactionStatus.POSTED, TransactionStatus.REVERSED)
        else None,
    )
    work.accounts.session.add(transaction_mapper.to_orm(source))
    work.accounts.session.flush()
    effect = replace(movement(source.id, account.id), amount=amount, direction=direction)
    work.accounts.session.add(account_movement_mapper.to_orm(effect))
    work.accounts.session.flush()


def test_atomic_zero_initialization_and_opening_metadata(work, account, migrated_engine):
    with work:
        balance = work.balances.get_by_account_id(account.id)
        opening = work.balances.get_opening(account.id)
        assert balance.booked_balance == balance.available_balance == 0
        assert opening.opening_balance == 0
        assert opening.policy is BalanceInitializationPolicy.ORDINARY
        assert opening.initialized_at == balance.updated_at
        assert work.accounts.session.scalar(text("SELECT count(*) FROM banking.transactions")) == 0
    assert migrated_engine.pool.checkedout() == 0


def test_account_creation_rolls_back_if_balance_initialization_fails(work, migrated_engine):
    def fail(self, *args, **kwargs):
        raise RuntimeError("Balance initialization failure")

    with patch.object(SQLAlchemyBalanceRepository, "create_initial_balance", fail):
        with pytest.raises(RuntimeError):
            CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    with migrated_engine.connect() as connection:
        for table in ("accounts", "account_balances", "account_balance_openings"):
            assert connection.scalar(text(f"SELECT count(*) FROM banking.{table}")) == 0


def test_credit_debit_and_insufficient_funds(work, account):
    with work:
        coordinator = service(work)
        assert coordinator.credit(account.id, Decimal("100"), currency="CZK").booked_balance == 100
        assert coordinator.debit(account.id, Decimal("40"), currency="CZK").available_balance == 60
        work.commit()
    assert read(work, account.id).booked_balance == 60
    with pytest.raises(InsufficientFunds), work:
        service(work).debit(account.id, Decimal("60.01"), currency="CZK")
    assert read(work, account.id).booked_balance == 60


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("NaN"), 1.0])
def test_invalid_operation_amounts_do_not_change_balances(work, account, amount):
    with pytest.raises(InvalidAccountBalanceData), work:
        service(work).credit(account.id, amount, currency="CZK")
    assert read(work, account.id).booked_balance == 0


def test_currency_missing_account_and_missing_projection(work, account):
    with pytest.raises(BalanceCurrencyMismatch), work:
        service(work).credit(account.id, Decimal("1"), currency="USD")
    with pytest.raises(AccountNotFound), work:
        service(work).initialize(uuid4(), currency="CZK")
    with work:
        raw = replace(account, id=uuid4(), account_number="not-initialized")
        work.accounts.save(raw)
        work.commit()
    with pytest.raises(BalanceNotFound), work:
        service(work).credit(raw.id, Decimal("1"), currency="CZK")
    assert read(work, raw.id) is None


def test_explicit_historical_initialization_never_resets_existing_balance(work, account):
    with work:
        historical = replace(account, id=uuid4(), account_number="historical")
        work.accounts.save(historical)
        work.commit()
    with pytest.raises(InvalidAccountBalanceData), work:
        service(work).initialize(historical.id, Decimal("-10"), currency="CZK")
    with work:
        balance = service(work).initialize(
            historical.id,
            Decimal("-10"),
            currency="CZK",
            policy=BalanceInitializationPolicy.HISTORICAL,
        )
        assert balance.available_balance == -10
        assert service(work).check_consistency(historical.id, currency="CZK").is_consistent
        work.commit()
    with pytest.raises(BalanceAlreadyInitialized), work:
        service(work).initialize(historical.id, Decimal("999"), currency="CZK")
    assert read(work, historical.id).booked_balance == -10
    with work:
        assert work.balances.get_opening(historical.id).opening_balance == -10


def test_duplicate_repository_initialization_is_rejected(work, account):
    with pytest.raises(BalanceAlreadyInitialized), work:
        work.balances.create_initial_balance(account.id, Decimal("100"))
    assert read(work, account.id).booked_balance == 0


def test_no_implicit_commits_and_multi_account_failure_is_atomic(work, account):
    other = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    with work:
        service(work).credit(account.id, Decimal("10"), currency="CZK")
        observer = SQLAlchemyAccountUnitOfWork(work.sessions)
        assert read(observer, account.id).booked_balance == 0
        # No commit: leave and discard this change.
    assert read(work, account.id).booked_balance == 0
    with pytest.raises(InsufficientFunds), work:
        service(work).lock_accounts([other.id, account.id], currency="CZK")
        service(work).credit(account.id, Decimal("10"), currency="CZK")
        service(work).debit(other.id, Decimal("1"), currency="CZK")
    assert read(work, account.id).booked_balance == read(work, other.id).booked_balance == 0


def test_balance_updates_require_a_fresh_transaction_lock(work, account):
    with work:
        snapshot = work.balances.get_by_account_id(account.id)
        with pytest.raises(BalanceLockRequired):
            work.balances.persist_updated_balance(snapshot.credit(Decimal("1")))
        locked = work.balances.get_for_update(account.id)
        repository = work.balances
        work.commit()
        with pytest.raises(BalanceLockRequired):
            repository.persist_updated_balance(locked.credit(Decimal("1")))
    assert read(work, account.id).booked_balance == 0


def test_locked_read_refreshes_stale_session_identity(work, account):
    with work:
        old = work.balances.get_by_account_id(account.id)
        contender = SQLAlchemyAccountUnitOfWork(work.sessions)
        with contender:
            service(contender).credit(account.id, Decimal("12"), currency="CZK")
            contender.commit()
        assert old.booked_balance == 0
        assert work.balances.get_for_update(account.id).booked_balance == 12


def test_repositories_do_not_own_session_lifecycle(work, account):
    def forbidden(*args, **kwargs):
        pytest.fail("Repository/service called commit, rollback or close")

    with work:
        with (
            patch.object(work.accounts.session, "commit", forbidden),
            patch.object(work.accounts.session, "rollback", forbidden),
            patch.object(work.accounts.session, "close", forbidden),
        ):
            service(work).credit(account.id, Decimal("1"), currency="CZK")
            assert work.balances.get_opening(account.id).opening_balance == 0
        work.commit()


@pytest.mark.parametrize("operation", ["credit", "debit"])
def test_concurrent_operations_wait_and_do_not_lose_updates(
    work, account, migrated_engine, operation
):
    if operation == "debit":
        with work:
            service(work).credit(account.id, Decimal("100"), currency="CZK")
            work.commit()
    amount = Decimal("10") if operation == "credit" else Decimal("80")

    def contender():
        concurrent = SQLAlchemyAccountUnitOfWork(work.sessions)
        with concurrent:
            changed = getattr(service(concurrent), operation)(account.id, amount, currency="CZK")
            concurrent.commit()
            return changed

    with ThreadPoolExecutor(max_workers=1) as pool:
        with work:
            getattr(service(work), operation)(account.id, amount, currency="CZK")
            future = pool.submit(contender)
            waiting = False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with migrated_engine.connect() as connection:
                    waiting = connection.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                            "AND pid <> pg_backend_pid())"
                        )
                    )
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting and not future.done()
            work.commit()
        if operation == "debit":
            with pytest.raises(InsufficientFunds):
                future.result(timeout=5)
        else:
            assert future.result(timeout=5).booked_balance == 20
    assert read(work, account.id).booked_balance == 20
    assert migrated_engine.pool.checkedout() == 0


def test_consistency_uses_explicit_opening_and_only_posted_signed_movements(work, account):
    with work:
        coordinator = service(work)
        assert coordinator.check_consistency(account.id, currency="CZK").is_consistent
        coordinator.credit(account.id, Decimal("5"), currency="CZK")
        assert not coordinator.check_consistency(account.id, currency="CZK").is_consistent
        add_movement(
            work, account, Decimal("5"), MovementDirection.CREDIT, TransactionStatus.REVERSED
        )
        coordinator.debit(account.id, Decimal("2"), currency="CZK")
        add_movement(work, account, Decimal("2"), MovementDirection.DEBIT)
        add_movement(
            work, account, Decimal("999"), MovementDirection.CREDIT, TransactionStatus.REJECTED
        )
        add_movement(
            work, account, Decimal("999"), MovementDirection.CREDIT, TransactionStatus.PENDING
        )
        result = coordinator.check_consistency(account.id, currency="CZK")
        assert result.is_consistent
        assert (
            result.opening_balance == 0
            and result.posted_movement_total == result.booked_balance == 3
        )
        work.commit()


def test_consistency_requires_known_opening_and_matching_movement_currency(work, account):
    with pytest.raises(BalanceOpeningNotFound), work:
        work.accounts.session.execute(
            text("DELETE FROM banking.account_balance_openings WHERE account_id = :id"),
            {"id": account.id},
        )
        service(work).check_consistency(account.id, currency="CZK")
    with pytest.raises(BalanceCurrencyMismatch), work:
        add_movement(work, account, Decimal("1"), MovementDirection.CREDIT, currency="EUR")
        service(work).check_consistency(account.id, currency="CZK")


def test_existing_posted_history_cannot_be_silently_initialized(work, account):
    with work:
        raw = replace(account, id=uuid4(), account_number="history-without-opening")
        work.accounts.save(raw)
        work.accounts.session.flush()
        add_movement(work, raw, Decimal("1"), MovementDirection.CREDIT)
        work.commit()
    with pytest.raises(BalanceInitializationRequiresReplay), work:
        service(work).initialize(
            raw.id, Decimal("1"), currency="CZK", policy=BalanceInitializationPolicy.HISTORICAL
        )
    assert read(work, raw.id) is None


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE banking.account_balances SET available_balance = 1",
        "UPDATE banking.account_balances SET booked_balance = 'NaN', available_balance = 'NaN'",
        "UPDATE banking.account_balance_openings SET opening_balance = -1, policy = 'ORDINARY'",
        "UPDATE banking.account_balance_openings SET policy = 'UNKNOWN'",
    ],
)
def test_database_checks(work, account, sql):
    with pytest.raises(IntegrityError), work:
        work.accounts.session.execute(text(sql))


def test_database_fk_and_unique_balance(work, account):
    with pytest.raises(IntegrityError), work:
        work.accounts.session.add(
            AccountBalanceORM(
                account_id=account.id,
                booked_balance=0,
                available_balance=0,
                updated_at=datetime.now(UTC),
            )
        )
        work.accounts.session.flush()
    with pytest.raises(IntegrityError), work:
        work.balances.create_initial_balance(uuid4())


def test_balance_migration_preserves_accounts_and_does_not_guess_backfill(
    isolated_database_settings,
):
    engine = create_database_engine(isolated_database_settings)
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "0002_create_transactions")
            account_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO banking.accounts "
                    "(id, customer_id, account_number, currency, opened_at, "
                    "created_at, updated_at) "
                    "VALUES (:id, :customer, 'pre-balance', 'CZK', CURRENT_DATE, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": account_id, "customer": uuid4()},
            )
            command.upgrade(config, "head")
            assert connection.scalar(text("SELECT count(*) FROM banking.account_balances")) == 0
            assert connection.scalar(text("SELECT count(*) FROM banking.accounts")) == 1
            assert (
                compare_metadata(
                    MigrationContext.configure(
                        connection, opts={"include_schemas": True, "compare_server_default": True}
                    ),
                    Base.metadata,
                )
                == []
            )
            command.downgrade(config, "0002_create_transactions")
            assert not inspect(connection).has_table("account_balances", schema="banking")
            assert not inspect(connection).has_table("account_balance_openings", schema="banking")
            assert connection.scalar(text("SELECT count(*) FROM banking.accounts")) == 1
            command.upgrade(config, "head")
            verify_head(connection, config)
    finally:
        engine.dispose()
