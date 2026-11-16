from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

import pytest

from application.account_balance_service import AccountBalanceService
from application.account_messages import CreateAccountCommand
from application.use_cases.create_account import CreateAccount
from domain.account.entities import Account
from domain.account_balance.entities import AccountBalance, BalanceOpening
from domain.account_balance.enums import BalanceInitializationPolicy
from domain.account_balance.exceptions import InsufficientFunds, InvalidAccountBalanceData
from infrastructure.persistence.mappers import balance_mapper
from ports.balance_repository import (
    BalanceAlreadyInitialized,
    BalanceCurrencyMismatch,
    BalanceNotFound,
)
from tests.account_fakes import FakeAccountUnitOfWork


def test_zero_initialization_and_immutable_domain():
    balance = AccountBalance.create_initial(uuid4())
    assert balance.booked_balance == balance.available_balance == Decimal("0")
    assert balance.updated_at.tzinfo is UTC
    before = asdict(balance)
    for field, value in before.items():
        with pytest.raises(FrozenInstanceError):
            setattr(balance, field, value)
    assert asdict(balance) == before


@pytest.mark.parametrize(
    "value", [1, 1.5, "1.00", Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), None]
)
def test_invalid_balances(value):
    with pytest.raises(InvalidAccountBalanceData):
        AccountBalance(uuid4(), value, value, datetime.now(UTC))


def test_projection_equality_and_references():
    with pytest.raises(InvalidAccountBalanceData, match="equal"):
        AccountBalance(uuid4(), Decimal("1"), Decimal("0"), datetime.now(UTC))
    with pytest.raises(InvalidAccountBalanceData, match="account_id"):
        AccountBalance.create_initial("invalid")


def test_historical_negative_policy_is_explicit():
    account_id = uuid4()
    with pytest.raises(InvalidAccountBalanceData, match="HISTORICAL"):
        AccountBalance.create_initial(account_id, Decimal("-10"))
    historical = AccountBalance.create_initial(
        account_id, Decimal("-10"), policy=BalanceInitializationPolicy.HISTORICAL
    )
    assert historical.booked_balance == Decimal("-10")
    assert AccountBalance(**asdict(historical)) == historical
    with pytest.raises(InsufficientFunds):
        historical.debit(Decimal("1"))
    with pytest.raises(InvalidAccountBalanceData, match="negative"):
        historical.credit(Decimal("1"))
    assert historical.credit(Decimal("10")).booked_balance == 0


def test_credit_and_debit_preserve_original_snapshot_and_precision():
    balance = AccountBalance.create_initial(uuid4(), Decimal("1234567890123456.78"))
    with localcontext() as context:
        context.prec = 2
        changed = balance.credit(Decimal("0.01")).debit(Decimal("0.02"))
    assert changed.booked_balance == Decimal("1234567890123456.77")
    assert changed.available_balance == changed.booked_balance
    assert balance.booked_balance == Decimal("1234567890123456.78")
    with pytest.raises(InsufficientFunds):
        AccountBalance.create_initial(uuid4()).debit(Decimal("0.01"))


@pytest.mark.parametrize(
    "amount", [Decimal("0"), Decimal("-1"), 1, True, Decimal("NaN"), Decimal("Infinity")]
)
@pytest.mark.parametrize("operation", ["credit", "debit"])
def test_operation_amounts_are_positive_decimals(amount, operation):
    balance = AccountBalance.create_initial(uuid4(), Decimal("10"))
    with pytest.raises(InvalidAccountBalanceData, match="amount"):
        getattr(balance, operation)(amount)


def test_mapper_round_trips_and_refuses_silent_rounding():
    balance = AccountBalance.create_initial(uuid4(), Decimal("10.25"))
    opening = BalanceOpening(
        balance.account_id,
        balance.booked_balance,
        BalanceInitializationPolicy.ORDINARY,
        balance.updated_at,
    )
    assert balance_mapper.to_domain(balance_mapper.to_orm(balance)) == balance
    assert balance_mapper.opening_to_domain(balance_mapper.opening_to_orm(opening)) == opening
    with pytest.raises(ValueError, match="NUMERIC"):
        balance_mapper.to_orm(balance.credit(Decimal("0.001")))


def test_create_account_initializes_balance_and_failure_rolls_back():
    work = FakeAccountUnitOfWork()
    account = CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    assert work.balances.rows[account.id].booked_balance == 0
    assert work.balances.openings[account.id].opening_balance == 0
    work.commit_error = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        CreateAccount(work).execute(CreateAccountCommand(uuid4()))
    assert len(work.accounts.rows) == len(work.balances.rows) == len(work.balances.openings) == 1


def test_service_locks_in_uuid_order_and_does_not_commit():
    work = FakeAccountUnitOfWork()
    for number in (2, 1):
        account = Account.create(
            customer_id=uuid4(),
            account_number=f"number-{number}",
            currency="CZK",
            opened_at=datetime.now(UTC).date(),
        )
        from dataclasses import replace

        account = replace(account, id=UUID(int=number))
        work.accounts.rows[account.id] = account
        work.balances.create_initial_balance(account.id)
    service = AccountBalanceService(work.accounts, work.balances)
    locked = service.lock_accounts([UUID(int=2), UUID(int=1), UUID(int=2)], currency="CZK")
    assert list(locked) == [UUID(int=1), UUID(int=2)]
    assert work.balances.calls == list(locked)
    assert service.credit(UUID(int=1), Decimal("5"), currency="CZK").booked_balance == 5
    assert work.commits == 0
    with pytest.raises(BalanceCurrencyMismatch):
        service.credit(UUID(int=1), Decimal("1"), currency="EUR")
    with pytest.raises(BalanceAlreadyInitialized):
        service.initialize(UUID(int=1), currency="CZK")
    del work.balances.rows[UUID(int=1)]
    with pytest.raises(BalanceNotFound):
        service.debit(UUID(int=1), Decimal("1"), currency="CZK")
