from typing import Protocol
from uuid import UUID


class CustomerIdentityUnavailable(RuntimeError):
    pass


class CustomerIdentityResolver(Protocol):
    def resolve_customer_id(self, actor_id: UUID) -> UUID | None: ...
