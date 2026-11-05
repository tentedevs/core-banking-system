from typing import Annotated, Literal
from uuid import UUID

from auth_client import ActorType, CurrentActor
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from api.authentication import get_current_actor
from api.dependencies import SessionDependency
from application.customer_identity import ResolveCustomerIdentity
from infrastructure.persistence.repositories.actor_customer_link_repository import (
    SQLAlchemyActorCustomerLinkRepository,
)

router = APIRouter(tags=["Identity"])


class MeResponse(BaseModel):
    actor_id: UUID
    actor_type: ActorType
    application_code: Literal["CBS"]
    customer_id: UUID | None
    link_status: Literal["LINKED", "PENDING_LINK", "NOT_APPLICABLE"]


@router.get("/me", response_model=MeResponse)
def me(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    session: SessionDependency,
    response: Response,
) -> MeResponse:
    response.headers["Cache-Control"] = "no-store"
    customer_id = None
    status: Literal["LINKED", "PENDING_LINK", "NOT_APPLICABLE"] = "NOT_APPLICABLE"
    if actor.actor_type is ActorType.CUSTOMER:
        if session is None:
            raise HTTPException(status_code=503, detail="Identity persistence unavailable")
        customer_id = ResolveCustomerIdentity(
            SQLAlchemyActorCustomerLinkRepository(session)
        ).resolve_customer_id(actor.actor_id)
        status = "LINKED" if customer_id else "PENDING_LINK"
    return MeResponse(
        actor_id=actor.actor_id,
        actor_type=actor.actor_type,
        application_code="CBS",
        customer_id=customer_id,
        link_status=status,
    )
