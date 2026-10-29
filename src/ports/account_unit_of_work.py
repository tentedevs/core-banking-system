from types import TracebackType
from typing import Protocol, Self

from ports.account_repository import AccountRepository


class AccountUnitOfWork(Protocol):
    """One transaction per context; exiting without commit discards writes.

    Each application execution owns an instance. It must not be shared across
    concurrent executions. Multiple repository operations share its transaction.
    """

    @property
    def accounts(self) -> AccountRepository: ...

    def __enter__(self) -> Self: ...

    def commit(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
