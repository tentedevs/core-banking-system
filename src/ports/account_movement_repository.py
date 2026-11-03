from typing import Protocol
from uuid import UUID

from domain.transaction.entities import AccountMovement


class AccountMovementRepository(Protocol):
    """Append-only movement records; no balance updates or transaction ownership."""

    def add(self, movement: AccountMovement) -> None: ...

    def list_by_account(
        self, account_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AccountMovement]: ...

    def count_by_account(self, account_id: UUID) -> int: ...

    def list_by_transaction(
        self, transaction_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AccountMovement]: ...

    def count_by_transaction(self, transaction_id: UUID) -> int: ...
