from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
from uuid import UUID

from domain.account_balance.enums import BalanceInitializationPolicy
from domain.account_balance.exceptions import InsufficientFunds, InvalidAccountBalanceData


def _money(value: object, field: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or (positive and value <= 0):
        raise InvalidAccountBalanceData(
            f"{field} must be a finite {'positive ' if positive else ''}Decimal"
        )


def _exact_sum(left: Decimal, right: Decimal) -> Decimal:
    a, b = left.as_tuple(), right.as_tuple()
    assert isinstance(a.exponent, int) and isinstance(b.exponent, int)
    scale = min(a.exponent, b.exponent)
    precision = max(len(a.digits) + a.exponent - scale, len(b.digits) + b.exponent - scale) + 1
    with localcontext(Context(prec=max(precision, 28))):
        return left + right


def _validate_opening(amount: Decimal, policy: BalanceInitializationPolicy) -> None:
    _money(amount, "initial_balance")
    if not isinstance(policy, BalanceInitializationPolicy):
        raise InvalidAccountBalanceData("policy must be a BalanceInitializationPolicy")
    if amount < 0 and policy is not BalanceInitializationPolicy.HISTORICAL:
        raise InvalidAccountBalanceData("negative opening balances require HISTORICAL policy")


@dataclass(frozen=True)
class AccountBalance:
    """Immutable balance snapshot. Negative reconstruction is historical only."""

    account_id: UUID
    booked_balance: Decimal
    available_balance: Decimal
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, UUID):
            raise InvalidAccountBalanceData("account_id must be a UUID")
        _money(self.booked_balance, "booked_balance")
        _money(self.available_balance, "available_balance")
        if self.available_balance != self.booked_balance:
            raise InvalidAccountBalanceData(
                "available_balance must equal booked_balance in this MVP"
            )
        if not isinstance(self.updated_at, datetime):
            raise InvalidAccountBalanceData("updated_at must be a datetime")

    @classmethod
    def create_initial(
        cls,
        account_id: UUID,
        initial_balance: Decimal = Decimal("0"),
        *,
        policy: BalanceInitializationPolicy = BalanceInitializationPolicy.ORDINARY,
    ) -> "AccountBalance":
        _validate_opening(initial_balance, policy)
        return cls(account_id, initial_balance, initial_balance, datetime.now(UTC))

    def credit(self, amount: Decimal) -> "AccountBalance":
        _money(amount, "amount", positive=True)
        updated = _exact_sum(self.booked_balance, amount)
        if updated < 0:
            raise InvalidAccountBalanceData("ordinary credits cannot leave a negative balance")
        return replace(
            self, booked_balance=updated, available_balance=updated, updated_at=datetime.now(UTC)
        )

    def debit(self, amount: Decimal) -> "AccountBalance":
        _money(amount, "amount", positive=True)
        if amount > self.available_balance:
            raise InsufficientFunds("Insufficient available funds")
        updated = _exact_sum(self.booked_balance, amount.copy_negate())
        return replace(
            self, booked_balance=updated, available_balance=updated, updated_at=datetime.now(UTC)
        )

    def is_consistent_with(self, opening_balance: Decimal, posted_movement_total: Decimal) -> bool:
        _money(opening_balance, "opening_balance")
        _money(posted_movement_total, "posted_movement_total")
        return _exact_sum(opening_balance, posted_movement_total) == self.booked_balance


@dataclass(frozen=True)
class BalanceOpening:
    """Immutable initialization metadata, separate from ordinary deposits."""

    account_id: UUID
    opening_balance: Decimal
    policy: BalanceInitializationPolicy
    initialized_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, UUID):
            raise InvalidAccountBalanceData("account_id must be a UUID")
        _validate_opening(self.opening_balance, self.policy)
        if not isinstance(self.initialized_at, datetime):
            raise InvalidAccountBalanceData("initialized_at must be a datetime")
