from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from domain.account_balance.entities import AccountBalance, BalanceOpening
from domain.account_balance.enums import BalanceInitializationPolicy


class BalanceNotFound(Exception):
    pass


class BalanceAlreadyInitialized(ValueError):
    pass


class BalanceLockRequired(RuntimeError):
    pass


class BalanceCurrencyMismatch(ValueError):
    pass


class BalanceInitializationRequiresReplay(ValueError):
    pass


class BalanceOpeningNotFound(Exception):
    pass


@dataclass(frozen=True)
class PostedMovementSummary:
    total: Decimal
    count: int


class BalanceRepository(Protocol):
    def get_by_account_id(self, account_id: UUID) -> AccountBalance | None: ...

    def create_initial_balance(
        self,
        account_id: UUID,
        initial_balance: Decimal = Decimal("0"),
        *,
        policy: BalanceInitializationPolicy = BalanceInitializationPolicy.ORDINARY,
    ) -> AccountBalance: ...

    def get_for_update(self, account_id: UUID) -> AccountBalance | None: ...

    def persist_updated_balance(self, balance: AccountBalance) -> None:
        """Require get_for_update in the same active transaction before persisting."""
        ...

    def get_opening(self, account_id: UUID) -> BalanceOpening | None: ...

    def get_posted_movement_summary(
        self, account_id: UUID, currency: str
    ) -> PostedMovementSummary: ...
