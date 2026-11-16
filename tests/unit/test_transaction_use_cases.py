from dataclasses import replace
from decimal import Decimal, localcontext
from unittest.mock import patch
from uuid import uuid4

import pytest

from application.account_messages import CreateAccountCommand
from application.transaction_messages import (
    CreateDepositCommand,
    CreateTransferCommand,
    CreateWithdrawalCommand,
    GetAccountBalanceQuery,
    GetTransactionQuery,
    ListAccountMovementsQuery,
    ListTransactionsQuery,
)
from application.transaction_posting import AccountNotActive, request_fingerprint
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
from ports.balance_repository import BalanceCurrencyMismatch, BalanceNotFound
from ports.transaction_repository import IdempotencyConflict
from tests.account_fakes import FakeAccountUnitOfWork


@pytest.fixture
def work():
    return FakeAccountUnitOfWork()


@pytest.fixture
def accounts(work):
    return [CreateAccount(work).execute(CreateAccountCommand(uuid4())) for _ in range(2)]


def deposit(work, account_id, amount="100", key="funding"):
    return CreateDeposit(work).execute(
        CreateDepositCommand(account_id, Decimal(amount), "CZK", key)
    )


def test_deposit_withdrawal_transfer_atomic_results(work, accounts):
    a, b = accounts
    before = work.commits
    deposited = deposit(work, a.id)
    withdrawn = CreateWithdrawal(work).execute(
        CreateWithdrawalCommand(a.id, Decimal("20"), "CZK", "w")
    )
    transferred = CreateTransfer(work).execute(
        CreateTransferCommand(a.id, b.id, Decimal("30"), "CZK", "t")
    )
    assert work.commits == before + 3
    assert work.balances.rows[a.id].booked_balance == 50
    assert work.balances.rows[b.id].available_balance == 30
    expected = [
        (deposited, [MovementDirection.CREDIT], [100]),
        (withdrawn, [MovementDirection.DEBIT], [80]),
        (transferred, [MovementDirection.DEBIT, MovementDirection.CREDIT], [50, 30]),
    ]
    for transaction, directions, balances in expected:
        assert transaction.status is TransactionStatus.POSTED
        assert transaction.posted_at is not None
        effects = [m for m in work.movements.rows.values() if m.transaction_id == transaction.id]
        assert [m.direction for m in effects] == directions
        assert [m.balance_after for m in effects] == balances
        assert all(m.booked_at == transaction.posted_at for m in effects)
    assert next(iter(work.movements.rows.values())).category == "SIMULATED_CASH_DEPOSIT"
    transfer_effects = [
        m for m in work.movements.rows.values() if m.transaction_id == transferred.id
    ]
    assert [m.counterparty_account for m in transfer_effects] == [
        b.account_number,
        a.account_number,
    ]
    assert work.balances.calls[:1] == [a.id]


@pytest.mark.parametrize("kind", ["deposit", "withdrawal", "transfer"])
def test_idempotent_writes_return_original_without_committing_again(work, accounts, kind):
    a, b = accounts
    deposit(work, a.id)
    use_case, command = {
        "deposit": (CreateDeposit, CreateDepositCommand(a.id, Decimal("1"), "CZK", "once")),
        "withdrawal": (
            CreateWithdrawal,
            CreateWithdrawalCommand(a.id, Decimal("1"), "CZK", "once"),
        ),
        "transfer": (
            CreateTransfer,
            CreateTransferCommand(a.id, b.id, Decimal("1"), "CZK", "once"),
        ),
    }[kind]
    original = use_case(work).execute(command)
    count = work.commits
    snapshot = dict(work.balances.rows)
    assert use_case(work).execute(replace(command, amount=Decimal("1.00"))) == original
    assert work.commits == count
    assert work.balances.rows == snapshot
    assert len(work.transactions.rows) == 2


@pytest.mark.parametrize(
    "field,value", [("amount", Decimal("2")), ("currency", "EUR"), ("description", "")]
)
def test_conflicting_payload(work, accounts, field, value):
    command = CreateDepositCommand(accounts[0].id, Decimal("1"), "CZK", "key")
    CreateDeposit(work).execute(command)
    with pytest.raises(IdempotencyConflict):
        CreateDeposit(work).execute(replace(command, **{field: value}))
    assert len(work.transactions.rows) == len(work.movements.rows) == 1


def test_fingerprint_includes_type_accounts_roles_and_is_decimal_context_independent(accounts):
    a, b = accounts
    original = CreateTransferCommand(a.id, b.id, Decimal("123.45"), "CZK", "key", "hello")
    with localcontext() as context:
        context.prec = 2
        first = request_fingerprint(original)
    assert first == request_fingerprint(replace(original, amount=Decimal("123.4500")))
    assert first != request_fingerprint(
        replace(original, source_account_id=b.id, destination_account_id=a.id)
    )
    deposit_command = CreateDepositCommand(a.id, original.amount, "CZK", "key", "hello")
    assert request_fingerprint(deposit_command) != request_fingerprint(
        CreateWithdrawalCommand(a.id, original.amount, "CZK", "key", "hello")
    )
    assert request_fingerprint(deposit_command) != request_fingerprint(
        replace(deposit_command, account_id=b.id)
    )


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal(".001"),
        Decimal("10000000000000000"),
        1,
        True,
        1.2,
        "1",
    ],
)
@pytest.mark.parametrize("command", [CreateDepositCommand, CreateWithdrawalCommand])
def test_invalid_live_amounts(command, amount):
    with pytest.raises(ValueError):
        command(uuid4(), amount, "CZK", "key")


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "eur"},
        {"currency": "EURO"},
        {"currency": "12A"},
        {"idempotency_key": ""},
        {"idempotency_key": " "},
        {"idempotency_key": "a" * 101},
        {"idempotency_key": None},
        {"account_id": "invalid"},
        {"description": 3},
    ],
)
def test_invalid_write_contract(changes):
    with pytest.raises(ValueError):
        CreateDepositCommand(
            **(
                dict(account_id=uuid4(), amount=Decimal("1"), currency="CZK", idempotency_key="key")
                | changes
            )
        )


def test_same_account_transfer_rejected():
    account_id = uuid4()
    with pytest.raises(ValueError, match="differ"):
        CreateTransferCommand(account_id, account_id, Decimal("1"), "CZK", "key")


@pytest.mark.parametrize("status", [AccountStatus.BLOCKED, AccountStatus.CLOSED])
def test_inactive_account_no_effects(work, accounts, status):
    from datetime import date

    account = accounts[0]
    work.accounts.rows[account.id] = replace(
        account, status=status, closed_at=date.today() if status is AccountStatus.CLOSED else None
    )
    with pytest.raises(AccountNotActive):
        deposit(work, account.id)
    assert not work.transactions.rows
    assert not work.movements.rows
    assert work.balances.rows[account.id].booked_balance == 0


@pytest.mark.parametrize(
    "scenario, error",
    [
        ("missing", AccountNotFound),
        ("currency", BalanceCurrencyMismatch),
        ("uninitialized", BalanceNotFound),
        ("funds", InsufficientFunds),
    ],
)
def test_business_failures_rollback(work, accounts, scenario, error):
    a, b = accounts
    if scenario == "missing":
        b = replace(b, id=uuid4())
    elif scenario == "currency":
        work.accounts.rows[b.id] = replace(b, currency="EUR")
    elif scenario == "uninitialized":
        del work.balances.rows[b.id]
    with pytest.raises(error):
        CreateTransfer(work).execute(
            CreateTransferCommand(a.id, b.id, Decimal("1"), "CZK", "failed")
        )
    assert not work.transactions.rows and not work.transactions.requests and not work.movements.rows
    assert work.balances.rows[a.id].booked_balance == 0


@pytest.mark.parametrize("phase", ["second_credit", "movement", "posting", "receipt", "commit"])
def test_partial_failure_rolls_back_all_rows(work, accounts, phase):
    a, b = accounts
    deposit(work, a.id)
    before = (
        dict(work.balances.rows),
        dict(work.transactions.rows),
        dict(work.movements.rows),
        dict(work.transactions.requests),
    )
    target, method = {
        "second_credit": (work.balances, "persist_updated_balance"),
        "movement": (work.movements, "add"),
        "posting": (work.transactions, "post"),
        "receipt": (work.transactions, "record_request"),
        "commit": (work, "commit"),
    }[phase]
    original = getattr(target, method)
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        original(*args, **kwargs)
        if phase != "second_credit" or calls == 2:
            raise RuntimeError("injected failure")

    # A failing real commit does not set the fake's committed flag.
    side_effect = RuntimeError("injected failure") if phase == "commit" else fail
    with patch.object(target, method, side_effect=side_effect), pytest.raises(RuntimeError):
        CreateTransfer(work).execute(
            CreateTransferCommand(a.id, b.id, Decimal("1"), "CZK", "failure")
        )
    assert (
        work.balances.rows,
        work.transactions.rows,
        work.movements.rows,
        work.transactions.requests,
    ) == before


def test_reads_filter_paginate_without_committing(work, accounts):
    a, b = accounts
    transaction = deposit(work, a.id)
    before = work.commits
    assert GetTransaction(work).execute(GetTransactionQuery(transaction.id)) == transaction
    assert ListTransactions(work).execute(
        ListTransactionsQuery(
            transaction_type=TransactionType.DEPOSIT, status=TransactionStatus.POSTED
        )
    ) == [transaction]
    assert (
        ListTransactions(work).execute(
            ListTransactionsQuery(transaction_type=TransactionType.TRANSFER)
        )
        == []
    )
    assert ListTransactions(work).execute(ListTransactionsQuery(offset=1)) == []
    assert len(ListAccountMovements(work).execute(ListAccountMovementsQuery(a.id))) == 1
    assert ListAccountMovements(work).execute(ListAccountMovementsQuery(b.id)) == []
    assert GetAccountBalance(work).execute(GetAccountBalanceQuery(a.id)).available_balance == 100
    assert work.commits == before
    with pytest.raises(TransactionNotFound):
        GetTransaction(work).execute(GetTransactionQuery(uuid4()))
    with pytest.raises(AccountNotFound):
        ListAccountMovements(work).execute(ListAccountMovementsQuery(uuid4()))
    with pytest.raises(AccountNotFound):
        GetAccountBalance(work).execute(GetAccountBalanceQuery(uuid4()))
    del work.balances.rows[a.id]
    with pytest.raises(BalanceNotFound):
        GetAccountBalance(work).execute(GetAccountBalanceQuery(a.id))


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"offset": -1},
        {"offset": False},
        {"transaction_type": "DEPOSIT"},
        {"status": "POSTED"},
    ],
)
def test_query_validation(changes):
    with pytest.raises(ValueError):
        ListTransactionsQuery(**changes)
