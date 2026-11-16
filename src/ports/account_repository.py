from typing import Protocol
from uuid import UUID

from domain.account.entities import Account


class AccountNumberConflict(ValueError):
    """The database rejected an account number already assigned to another identity."""


class AccountRepository(Protocol):
    """Domain-facing port; the caller owns the transaction.

    Collections are ordered by UUID, with 1 <= limit <= 100 and offset >= 0.
    Pagination arguments must be integers (booleans are not accepted).
    """

    def save(self, account: Account) -> None:
        """Insert a new identity or update lifecycle fields of an existing one.

        Existing identity, customer, account number, product, currency, opening
        date and creation timestamp are preserved. No transaction is committed.
        """
        ...

    def get_by_id(self, account_id: UUID) -> Account | None: ...

    def get_by_id_for_update(self, account_id: UUID) -> Account | None:
        """Read current state while holding a row lock until the transaction ends."""
        ...

    def get_by_account_number(self, account_number: str) -> Account | None: ...

    def list_by_customer(
        self, customer_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Account]: ...

    def list_all(self, limit: int = 50, offset: int = 0) -> list[Account]: ...

    def count(self, customer_id: UUID | None = None) -> int: ...
