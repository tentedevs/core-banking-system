from datetime import date
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from domain.account.enums import AccountProductType, AccountStatus


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID = Field(
        description="Customer identity; existence is not yet verified in CRP."
    )
    currency: str = Field(
        default="CZK", description="Three uppercase letters; ISO membership unchecked."
    )


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    account_number: str
    product_type: AccountProductType
    currency: str
    status: AccountStatus
    opened_at: date
    closed_at: date | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class AccountPagination(BaseModel):
    limit: int
    offset: int
    total_items: int
    total_pages: int

    @classmethod
    def from_total(cls, limit: int, offset: int, total_items: int) -> "AccountPagination":
        return cls(
            limit=limit,
            offset=offset,
            total_items=total_items,
            total_pages=(total_items + limit - 1) // limit,
        )


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    pagination: AccountPagination


class ErrorResponse(BaseModel):
    detail: str | list[dict[str, JsonValue]]
