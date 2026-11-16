import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from domain.transaction.enums import TransactionStatus, TransactionType


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise ValueError("Account and transaction identifiers must be UUIDs")


def _pagination(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")


def _write(amount: Decimal, currency: str, key: str, description: str | None) -> None:
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be a finite, positive Decimal")
    # Live operations must be exactly representable by NUMERIC(18, 2); never round money.
    if amount > Decimal("9999999999999999.99"):
        raise ValueError("amount exceeds the supported monetary range")
    _, digits, exponent = amount.as_tuple()
    assert isinstance(exponent, int)
    if exponent < -2 and any(digits[max(0, len(digits) + exponent + 2) :]):
        raise ValueError("amount must be exactly representable with two decimal places")
    if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("currency must be three uppercase ASCII letters")
    if not isinstance(key, str) or not key.strip() or len(key) > 100:
        raise ValueError("idempotency_key must contain between 1 and 100 characters")
    if description is not None and not isinstance(description, str):
        raise ValueError("description must be a string or None")


@dataclass(frozen=True)
class CreateDepositCommand:
    account_id: UUID
    amount: Decimal
    currency: str
    idempotency_key: str
    description: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.account_id)
        _write(self.amount, self.currency, self.idempotency_key, self.description)


@dataclass(frozen=True)
class CreateWithdrawalCommand:
    account_id: UUID
    amount: Decimal
    currency: str
    idempotency_key: str
    description: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.account_id)
        _write(self.amount, self.currency, self.idempotency_key, self.description)


@dataclass(frozen=True)
class CreateTransferCommand:
    source_account_id: UUID
    destination_account_id: UUID
    amount: Decimal
    currency: str
    idempotency_key: str
    description: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.source_account_id)
        _uuid(self.destination_account_id)
        if self.source_account_id == self.destination_account_id:
            raise ValueError("Source and destination accounts must differ")
        _write(self.amount, self.currency, self.idempotency_key, self.description)


@dataclass(frozen=True)
class GetTransactionQuery:
    transaction_id: UUID

    def __post_init__(self) -> None:
        _uuid(self.transaction_id)


@dataclass(frozen=True)
class ListTransactionsQuery:
    limit: int = 50
    offset: int = 0
    transaction_type: TransactionType | None = None
    status: TransactionStatus | None = None

    def __post_init__(self) -> None:
        _pagination(self.limit, self.offset)
        if self.transaction_type is not None and not isinstance(
            self.transaction_type, TransactionType
        ):
            raise ValueError("transaction_type must be a TransactionType")
        if self.status is not None and not isinstance(self.status, TransactionStatus):
            raise ValueError("status must be a TransactionStatus")


@dataclass(frozen=True)
class ListAccountMovementsQuery:
    account_id: UUID
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        _uuid(self.account_id)
        _pagination(self.limit, self.offset)


@dataclass(frozen=True)
class GetAccountBalanceQuery:
    account_id: UUID

    def __post_init__(self) -> None:
        _uuid(self.account_id)


@dataclass(frozen=True)
class ListTransactionMovementsQuery:
    transaction_id: UUID
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        _uuid(self.transaction_id)
        _pagination(self.limit, self.offset)
