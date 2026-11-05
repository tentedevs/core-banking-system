from uuid import UUID

from domain.customer_identity.entities import ActorCustomerLink
from ports.actor_customer_link_repository import ActorCustomerLinkRepository
from ports.customer_directory import CustomerDirectory, CustomerNotFound


class ResolveCustomerIdentity:
    def __init__(self, links: ActorCustomerLinkRepository) -> None:
        self.links = links

    def resolve_customer_id(self, actor_id: UUID) -> UUID | None:
        link = self.links.get_by_actor_id(actor_id)
        return link.customer_id if link else None


class LinkActorToCustomer:
    def __init__(self, links: ActorCustomerLinkRepository, customers: CustomerDirectory) -> None:
        self.links = links
        self.customers = customers

    def execute(self, actor_id: UUID, customer_id: UUID) -> ActorCustomerLink:
        if not self.customers.exists(customer_id):
            raise CustomerNotFound("Customer does not exist in CRP")
        return self.links.create_link(actor_id, customer_id)
