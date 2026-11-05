"""Trusted auth coordinator only; never proxy this route to browsers."""

import hashlib
import hmac
import re
from typing import Annotated
from uuid import UUID

from auth_client import ActorType, CurrentActor
from fastapi import APIRouter, Depends, HTTPException, Request

from api.dependencies import AccountWorkDependency
from api.routers.customer_onboarding import OnboardingRequest, provision_account

router = APIRouter(prefix="/internal/registrations", tags=["Internal registration"])


def trusted_registration(request: Request) -> None:
    if any(key == "origin" or key.startswith("sec-fetch-") for key in request.headers):
        raise HTTPException(status_code=403, detail="Forbidden")
    credential = request.app.state.settings.registration_service_credential
    values = request.headers.getlist("authorization")
    supplied = values[0][7:] if len(values) == 1 and values[0].startswith("Bearer ") else ""
    expected = credential.get_secret_value() if credential else ""
    matches = hmac.compare_digest(
        hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(expected.encode()).digest()
    )
    if (
        not credential
        or re.fullmatch(r"[0-9a-f]{64}", supplied) is None
        or not matches
        or request.headers.getlist("x-service-id") != ["auth-registration"]
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


TrustedRegistration = Annotated[None, Depends(trusted_registration)]


@router.put("/{actor_id}")
def register_customer(
    actor_id: UUID,
    payload: OnboardingRequest,
    work: AccountWorkDependency,
    request: Request,
    trusted: TrustedRegistration,
) -> dict[str, UUID | str]:
    # Only the authenticated coordinator establishes this identity. Browser actors/IDs
    # are never accepted on the public registration contract.
    from fastapi import Response

    account = provision_account(
        payload, CurrentActor(actor_id, "CBS", ActorType.CUSTOMER), work, request, Response()
    )
    return {"actor_id": actor_id, "customer_id": account.customer_id, "status": "LINKED"}


@router.get("/{actor_id}")
def registration_status(
    actor_id: UUID, work: AccountWorkDependency, trusted: TrustedRegistration
) -> dict[str, UUID | str]:
    with work:
        work.onboardings.lock_actor(actor_id)
        receipt = work.onboardings.get(actor_id)
        link = work.links.get_by_actor_id_for_update(actor_id)
        if (
            receipt is None
            or receipt.account_id is None
            or link is None
            or link.customer_id != receipt.customer_id
            or work.accounts.get_by_id(receipt.account_id) is None
        ):
            raise HTTPException(status_code=409, detail="Registration incomplete")
        return {"actor_id": actor_id, "customer_id": link.customer_id, "status": "LINKED"}
