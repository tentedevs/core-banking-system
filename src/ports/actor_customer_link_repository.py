from typing import Protocol
from uuid import UUID

from domain.customer_identity.entities import ActorCustomerLink


class ActorAlreadyLinked(ValueError):
    pass


class ActorCustomerLinkRepository(Protocol):
    def get_by_actor_id(self, actor_id: UUID) -> ActorCustomerLink | None: ...
    def get_by_actor_id_for_update(self, actor_id: UUID) -> ActorCustomerLink | None: ...
    def create_link(self, actor_id: UUID, customer_id: UUID) -> ActorCustomerLink: ...
    def remove_link(self, actor_id: UUID) -> None: ...
