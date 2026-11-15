from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class CustomerAccountOpening:
    customer_id: UUID
    account_id: UUID
    currency: str


class AccountOpeningRepository(Protocol):
    def lock_customer(self, customer_id: UUID) -> None: ...
    def get(self, customer_id: UUID) -> CustomerAccountOpening | None: ...
    def add(self, opening: CustomerAccountOpening) -> None: ...
