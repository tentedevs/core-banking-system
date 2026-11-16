from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.customer_identity.entities import ActorCustomerLink
from infrastructure.persistence.models import ActorCustomerLinkORM
from ports.actor_customer_link_repository import ActorAlreadyLinked


class SQLAlchemyActorCustomerLinkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_actor_id(self, actor_id: UUID) -> ActorCustomerLink | None:
        row = self.session.get(ActorCustomerLinkORM, actor_id, populate_existing=True)
        return ActorCustomerLink(row.actor_id, row.customer_id, row.created_at) if row else None

    def get_by_actor_id_for_update(self, actor_id: UUID) -> ActorCustomerLink | None:
        row = self.session.scalar(
            select(ActorCustomerLinkORM)
            .where(ActorCustomerLinkORM.actor_id == actor_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return ActorCustomerLink(row.actor_id, row.customer_id, row.created_at) if row else None

    def create_link(self, actor_id: UUID, customer_id: UUID) -> ActorCustomerLink:
        link = ActorCustomerLink(actor_id, customer_id, datetime.now(UTC))
        if self.get_by_actor_id(actor_id) is not None:
            raise ActorAlreadyLinked("Actor already has a customer link")
        self.session.add(
            ActorCustomerLinkORM(
                actor_id=link.actor_id, customer_id=link.customer_id, created_at=link.created_at
            )
        )
        try:
            self.session.flush()
        except IntegrityError as error:
            if (
                getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                != "pk_actor_customer_links"
            ):
                raise
            raise ActorAlreadyLinked("Actor already has a customer link") from None
        return link

    def remove_link(self, actor_id: UUID) -> None:
        self.session.execute(
            delete(ActorCustomerLinkORM).where(ActorCustomerLinkORM.actor_id == actor_id)
        )
