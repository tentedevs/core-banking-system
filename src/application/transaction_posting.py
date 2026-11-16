import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from application.account_balance_service import AccountBalanceService
from application.transaction_messages import (
    CreateDepositCommand,
    CreateTransferCommand,
    CreateWithdrawalCommand,
)
from domain.account.enums import AccountStatus
from domain.account_balance.entities import AccountBalance
from domain.transaction.entities import AccountMovement, BankingTransaction
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType
from ports.account_unit_of_work import AccountUnitOfWork
from ports.transaction_repository import IdempotencyConflict, IdempotencyRecord


class AccountNotActive(ValueError):
    """A live monetary operation requires every participating account to be ACTIVE."""


MonetaryCommand = CreateDepositCommand | CreateWithdrawalCommand | CreateTransferCommand


def request_fingerprint(command: MonetaryCommand) -> str:
    """Versioned, context-independent canonical financial request identity."""
    payload = {
        "version": "1",
        "amount": format(command.amount, ".2f"),
        "currency": command.currency,
        "description": command.description,
    }
    if isinstance(command, CreateTransferCommand):
        payload.update(
            operation=TransactionType.TRANSFER.value,
            source_account_id=str(command.source_account_id),
            destination_account_id=str(command.destination_account_id),
        )
    else:
        payload.update(
            operation=(
                TransactionType.DEPOSIT.value
                if isinstance(command, CreateDepositCommand)
                else TransactionType.WITHDRAWAL.value
            ),
            account_id=str(command.account_id),
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def post_operation(
    unit_of_work: AccountUnitOfWork,
    command: MonetaryCommand,
    authorize: Callable[[AccountUnitOfWork], None] | None = None,
) -> BankingTransaction:
    """Coordinate posting exclusively inside a caller-owned, atomic Unit of Work.

    Lock order: idempotency key, then all participating accounts/balances in UUID
    order. Account locks remain held through commit, including status validation.
    """
    fingerprint = request_fingerprint(command)
    with unit_of_work as work:
        transactions = work.transactions
        transactions.lock_idempotency_key(command.idempotency_key)
        # Customer authorization runs inside this transaction, before any receipt
        # can disclose an earlier result. Financial posting remains unchanged.
        if authorize is not None:
            authorize(work)
        receipt = transactions.get_request(command.idempotency_key)
        if receipt is not None:
            if receipt.fingerprint != fingerprint:
                raise IdempotencyConflict("Idempotency key belongs to a different request")
            original = transactions.get_by_id(receipt.transaction_id)
            if original is None:
                raise RuntimeError("Idempotency record references a missing transaction")
            return original
        if transactions.get_by_idempotency_key(command.idempotency_key) is not None:
            raise IdempotencyConflict(
                "Existing idempotency key has no verifiable request fingerprint"
            )

        service = AccountBalanceService(work.accounts, work.balances)
        ids = (
            [command.source_account_id, command.destination_account_id]
            if isinstance(command, CreateTransferCommand)
            else [command.account_id]
        )
        service.lock_accounts(ids, currency=command.currency)
        accounts = {}
        for account_id in ids:
            # The coordinator already holds the account row lock. No concurrent
            # block/close can change this state before this operation commits.
            account = work.accounts.get_by_id(account_id)
            if account is None:
                raise RuntimeError("Locked account disappeared")
            if account.status is not AccountStatus.ACTIVE:
                raise AccountNotActive(f"Account {account_id} must be ACTIVE")
            accounts[account_id] = account

        kind = (
            TransactionType.TRANSFER
            if isinstance(command, CreateTransferCommand)
            else TransactionType.DEPOSIT
            if isinstance(command, CreateDepositCommand)
            else TransactionType.WITHDRAWAL
        )
        pending = BankingTransaction.create(
            transaction_type=kind,
            amount=command.amount,
            currency=command.currency,
            effective_at=datetime.now(UTC),
            description=command.description,
            idempotency_key=command.idempotency_key,
        )
        transactions.add(pending)
        changes: list[tuple[AccountBalance, MovementDirection, str | None]]
        if isinstance(command, CreateTransferCommand):
            source = service.debit(
                command.source_account_id, command.amount, currency=command.currency
            )
            destination = service.credit(
                command.destination_account_id, command.amount, currency=command.currency
            )
            changes = [
                (
                    source,
                    MovementDirection.DEBIT,
                    accounts[command.destination_account_id].account_number,
                ),
                (
                    destination,
                    MovementDirection.CREDIT,
                    accounts[command.source_account_id].account_number,
                ),
            ]
            category = "INTERNAL_TRANSFER"
        elif isinstance(command, CreateDepositCommand):
            balance = service.credit(command.account_id, command.amount, currency=command.currency)
            changes = [(balance, MovementDirection.CREDIT, None)]
            category = "SIMULATED_CASH_DEPOSIT"
        else:
            balance = service.debit(command.account_id, command.amount, currency=command.currency)
            changes = [(balance, MovementDirection.DEBIT, None)]
            category = "CASH_WITHDRAWAL"

        posted_at = datetime.now(UTC)
        for balance, direction, counterparty in changes:
            work.movements.add(
                AccountMovement.create(
                    transaction_id=pending.id,
                    account_id=balance.account_id,
                    direction=direction,
                    amount=command.amount,
                    booked_at=posted_at,
                    balance_after=balance.booked_balance,
                    category=category,
                    counterparty_account=counterparty,
                )
            )
        posted = replace(pending, status=TransactionStatus.POSTED, posted_at=posted_at)
        transactions.post(posted)
        transactions.record_request(
            command.idempotency_key, IdempotencyRecord(fingerprint, posted.id)
        )
        work.commit()
        return posted
