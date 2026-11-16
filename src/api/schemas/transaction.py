from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from api.schemas.account import AccountPagination
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType

Money = Annotated[
    Decimal, PlainSerializer(lambda value: format(value, ".2f"), return_type=str, when_used="json")
]


class MonetaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(
        gt=0,
        max_digits=18,
        decimal_places=2,
        allow_inf_nan=False,
        description=(
            "Positive decimal string, at most 16 integer digits and 2 "
            "fractional digits; never rounded."
        ),
        examples=["500.00"],
    )
    currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description=(
            "Three uppercase ASCII letters, matching the account; ISO membership unchecked."
        ),
    )
    description: str | None = None

    @field_validator("amount", mode="before", json_schema_input_type=str)
    @classmethod
    def require_decimal_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("amount must be supplied as a decimal string")
        return value


class DepositRequest(MonetaryRequest):
    account_id: UUID


class WithdrawalRequest(MonetaryRequest):
    account_id: UUID


class TransferRequest(MonetaryRequest):
    source_account_id: UUID
    destination_account_id: UUID

    @model_validator(mode="after")
    def distinct_accounts(self) -> Self:
        if self.source_account_id == self.destination_account_id:
            raise ValueError("Source and destination accounts must differ")
        return self


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_type: TransactionType
    status: TransactionStatus = Field(
        description=(
            "PENDING, POSTED, REJECTED or REVERSED. Successful monetary writes return POSTED."
        )
    )
    amount: Money
    currency: str
    description: str | None
    effective_at: AwareDatetime
    posted_at: AwareDatetime | None
    idempotency_key: str | None
    reversal_of_id: UUID | None
    created_at: AwareDatetime


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    account_id: UUID
    direction: MovementDirection
    amount: Money
    balance_after: Money | None
    category: str | None
    counterparty_account: str | None
    counterparty_bank: str | None
    booked_at: AwareDatetime


class BalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    booked_balance: Money
    available_balance: Money
    updated_at: AwareDatetime


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    pagination: AccountPagination


class MovementListResponse(BaseModel):
    items: list[MovementResponse]
    pagination: AccountPagination
