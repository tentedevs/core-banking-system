from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from api.schemas.account import AccountPagination
from api.schemas.transaction import Money
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType


class CustomerMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transaction_id: UUID
    account_id: UUID
    direction: MovementDirection
    amount: Money
    balance_after: Money | None
    booked_at: AwareDatetime


class CustomerMovementListResponse(BaseModel):
    items: list[CustomerMovementResponse]
    pagination: AccountPagination


class CustomerTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transaction_type: TransactionType
    status: TransactionStatus
    amount: Money
    currency: str
    description: str | None
    effective_at: AwareDatetime
    posted_at: AwareDatetime | None


class CustomerTransactionListResponse(BaseModel):
    items: list[CustomerTransactionResponse]
    pagination: AccountPagination


class CustomerTransactionDetailResponse(CustomerTransactionResponse):
    movements: CustomerMovementListResponse
