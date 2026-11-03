from typing import Protocol
from uuid import UUID

from domain.transaction.entities import BankingTransaction
from domain.transaction.enums import TransactionStatus, TransactionType


class IdempotencyConflict(ValueError):
    """The key is already associated with another or unverifiable request."""


class TransactionPersistenceConflict(ValueError):
    """An attempted posting would overwrite an existing financial record."""


class TransactionRepository(Protocol):
    def add(self, transaction: BankingTransaction) -> None: ...

    def post(self, transaction: BankingTransaction) -> None: ...

    def get_by_id(self, transaction_id: UUID) -> BankingTransaction | None: ...

    def get_by_idempotency_key(self, key: str) -> BankingTransaction | None: ...

    def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
    ) -> list[BankingTransaction]: ...

    def count(
        self,
        *,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
    ) -> int: ...
