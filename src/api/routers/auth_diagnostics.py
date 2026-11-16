from typing import Annotated, Literal
from uuid import UUID

from auth_client import ActorType, CurrentActor
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from api.authentication import get_current_actor

router = APIRouter(prefix="/dev/auth", tags=["Development authentication"])


class VerifiedActorResponse(BaseModel):
    actor_id: UUID
    application_code: Literal["CBS"]
    actor_type: ActorType


@router.get("/whoami", response_model=VerifiedActorResponse)
def whoami(
    actor: Annotated[CurrentActor, Depends(get_current_actor)], response: Response
) -> VerifiedActorResponse:
    response.headers["Cache-Control"] = "no-store"
    return VerifiedActorResponse(
        actor_id=actor.actor_id, application_code="CBS", actor_type=actor.actor_type
    )
