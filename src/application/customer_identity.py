from dataclasses import dataclass
from uuid import UUID

from domain.customer_identity.entities import ActorCustomerLink
from ports.actor_customer_link_repository import ActorCustomerLinkRepository
from ports.customer_directory import CustomerDirectory, CustomerNotFound
from ports.customer_identity import CustomerIdentityResolver


@dataclass(frozen=True)
class VerifiedCustomerIdentity:
    """An immutable identity snapshot, scoped to one authenticated operation."""

    actor_id: UUID
    customer_id: UUID | None

    def resolve_customer_id(self, actor_id: UUID) -> UUID | None:
        return self.customer_id if actor_id == self.actor_id else None


class ResolveCustomerIdentity:
    def __init__(self, links: CustomerIdentityResolver) -> None:
        self.links = links

    def resolve_customer_id(self, actor_id: UUID) -> UUID | None:
        return self.links.resolve_customer_id(actor_id)


class LinkActorToCustomer:
    def __init__(self, links: ActorCustomerLinkRepository, customers: CustomerDirectory) -> None:
        self.links = links
        self.customers = customers

    def execute(self, actor_id: UUID, customer_id: UUID) -> ActorCustomerLink:
        if not self.customers.exists(customer_id):
            raise CustomerNotFound("Customer does not exist in CRP")
        return self.links.create_link(actor_id, customer_id)
