from dataclasses import dataclass
from uuid import UUID


def _validate_id(value: UUID, field: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field} must be a UUID")


@dataclass(frozen=True)
class CreateAccountCommand:
    customer_id: UUID
    currency: str = "CZK"

    def __post_init__(self) -> None:
        _validate_id(self.customer_id, "customer_id")
        # Currency invariants are validated by the existing Account factory.


@dataclass(frozen=True)
class GetAccountQuery:
    account_id: UUID

    def __post_init__(self) -> None:
        _validate_id(self.account_id, "account_id")


@dataclass(frozen=True)
class GetAccountByNumberQuery:
    account_number: str

    def __post_init__(self) -> None:
        if not isinstance(self.account_number, str) or not self.account_number.strip():
            raise ValueError("account_number must be a non-empty string")


@dataclass(frozen=True)
class ListAccountsQuery:
    customer_id: UUID | None = None
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if self.customer_id is not None:
            _validate_id(self.customer_id, "customer_id")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if type(self.offset) is not int or self.offset < 0:
            raise ValueError("offset must be a non-negative integer")


@dataclass(frozen=True)
class BlockAccountCommand:
    account_id: UUID

    def __post_init__(self) -> None:
        _validate_id(self.account_id, "account_id")


@dataclass(frozen=True)
class ReactivateAccountCommand:
    account_id: UUID

    def __post_init__(self) -> None:
        _validate_id(self.account_id, "account_id")
