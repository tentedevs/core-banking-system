from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ActorCustomerLink:
    actor_id: UUID
    customer_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, UUID) or not isinstance(self.customer_id, UUID):
            raise ValueError("Actor and customer identifiers must be UUIDs")
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
        ):
            raise ValueError("Link creation time must be timezone-aware")
