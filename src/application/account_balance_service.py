from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from application.use_cases.get_account import AccountNotFound
from domain.account.entities import Account
from domain.account_balance.entities import AccountBalance
from domain.account_balance.enums import BalanceInitializationPolicy
from ports.account_repository import AccountRepository
from ports.balance_repository import (
    BalanceAlreadyInitialized,
    BalanceCurrencyMismatch,
    BalanceInitializationRequiresReplay,
    BalanceNotFound,
    BalanceOpeningNotFound,
    BalanceRepository,
)


@dataclass(frozen=True)
class BalanceConsistency:
    account_id: UUID
    opening_balance: Decimal
    posted_movement_total: Decimal
    booked_balance: Decimal
    is_consistent: bool


class AccountBalanceService:
    """Internal coordination in the caller's Unit of Work; never commits."""

    def __init__(self, accounts: AccountRepository, balances: BalanceRepository) -> None:
        self.accounts = accounts
        self.balances = balances

    def _account(self, account_id: UUID, currency: str) -> Account:
        account = self.accounts.get_by_id_for_update(account_id)
        if account is None:
            raise AccountNotFound(f"Account {account_id} not found")
        if account.currency != currency:
            raise BalanceCurrencyMismatch("Operation currency does not match the account")
        return account

    def lock_accounts(
        self, account_ids: Iterable[UUID], *, currency: str
    ) -> dict[UUID, AccountBalance]:
        """Future multi-account operations must lock their full set first in UUID order."""
        locked = {}
        for account_id in sorted(set(account_ids), key=lambda value: value.int):
            self._account(account_id, currency)
            balance = self.balances.get_for_update(account_id)
            if balance is None:
                raise BalanceNotFound(f"Balance for account {account_id} is not initialized")
            locked[account_id] = balance
        return locked

    def initialize(
        self,
        account_id: UUID,
        opening_balance: Decimal = Decimal("0"),
        *,
        currency: str,
        policy: BalanceInitializationPolicy = BalanceInitializationPolicy.ORDINARY,
    ) -> AccountBalance:
        self._account(account_id, currency)
        if self.balances.get_by_account_id(account_id) is not None:
            raise BalanceAlreadyInitialized("Account balance is already initialized")
        summary = self.balances.get_posted_movement_summary(account_id, currency)
        if summary.count:
            raise BalanceInitializationRequiresReplay(
                "Posted movements already exist; controlled reconstruction is required "
                "before initialization"
            )
        return self.balances.create_initial_balance(account_id, opening_balance, policy=policy)

    def credit(self, account_id: UUID, amount: Decimal, *, currency: str) -> AccountBalance:
        balance = self.lock_accounts([account_id], currency=currency)[account_id]
        changed = balance.credit(amount)
        self.balances.persist_updated_balance(changed)
        return changed

    def debit(self, account_id: UUID, amount: Decimal, *, currency: str) -> AccountBalance:
        balance = self.lock_accounts([account_id], currency=currency)[account_id]
        changed = balance.debit(amount)
        self.balances.persist_updated_balance(changed)
        return changed

    def check_consistency(self, account_id: UUID, *, currency: str) -> BalanceConsistency:
        balance = self.lock_accounts([account_id], currency=currency)[account_id]
        opening = self.balances.get_opening(account_id)
        if opening is None:
            raise BalanceOpeningNotFound(
                "An explicit opening balance is required for reconciliation"
            )
        summary = self.balances.get_posted_movement_summary(account_id, currency)
        return BalanceConsistency(
            account_id,
            opening.opening_balance,
            summary.total,
            balance.booked_balance,
            balance.is_consistent_with(opening.opening_balance, summary.total),
        )
