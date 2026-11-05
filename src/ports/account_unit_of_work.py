from types import TracebackType
from typing import Protocol, Self

from ports.account_movement_repository import AccountMovementRepository
from ports.account_repository import AccountRepository
from ports.actor_customer_link_repository import ActorCustomerLinkRepository
from ports.balance_repository import BalanceRepository
from ports.customer_onboarding import CustomerOnboardingRepository
from ports.transaction_repository import TransactionRepository


class AccountUnitOfWork(Protocol):
    """One transaction per context; exiting without commit discards writes.

    Each application execution owns an instance. It must not be shared across
    concurrent executions. Multiple repository operations share its transaction.
    """

    @property
    def onboardings(self) -> CustomerOnboardingRepository: ...

    @property
    def links(self) -> ActorCustomerLinkRepository: ...

    @property
    def accounts(self) -> AccountRepository: ...

    @property
    def balances(self) -> BalanceRepository: ...

    @property
    def transactions(self) -> TransactionRepository: ...

    @property
    def movements(self) -> AccountMovementRepository: ...

    def __enter__(self) -> Self: ...

    def commit(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
