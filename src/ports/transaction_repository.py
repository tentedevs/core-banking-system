from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from domain.transaction.entities import BankingTransaction
from domain.transaction.enums import TransactionStatus, TransactionType


class IdempotencyConflict(ValueError):
    """The key is already associated with another or unverifiable request."""


class TransactionPersistenceConflict(ValueError):
    """An attempted posting would overwrite an existing financial record."""


@dataclass(frozen=True)
class IdempotencyRecord:
    fingerprint: str
    transaction_id: UUID


class TransactionRepository(Protocol):
    def add(self, transaction: BankingTransaction) -> None: ...

    def post(self, transaction: BankingTransaction) -> None: ...

    def get_by_id(self, transaction_id: UUID) -> BankingTransaction | None: ...

    def get_by_idempotency_key(self, key: str) -> BankingTransaction | None: ...

    def lock_idempotency_key(self, key: str) -> None:
        """Serialize requests for this key until the caller's transaction ends."""
        ...

    def get_request(self, key: str) -> IdempotencyRecord | None: ...

    def record_request(self, key: str, record: IdempotencyRecord) -> None: ...

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
