import hashlib
import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime

from api.dependencies import SessionDependency
from application.use_cases.read_risk_evidence import ReadRiskEvidence
from infrastructure.persistence.repositories.risk_evidence import SQLAlchemyRiskEvidenceQuery


def trusted_risk(request: Request) -> None:
    if any(key == "origin" or key.startswith("sec-fetch-") for key in request.headers):
        raise HTTPException(403, "Forbidden")
    credential = request.app.state.settings.risk_service_credential
    values = request.headers.getlist("authorization")
    token = values[0][7:] if len(values) == 1 and values[0].startswith("Bearer ") else ""
    expected = credential.get_secret_value() if credential else ""
    matches = hmac.compare_digest(
        hashlib.sha256(token.encode()).digest(), hashlib.sha256(expected.encode()).digest()
    )
    if not credential or not matches or request.headers.getlist("x-service-id") != ["crp-backend"]:
        raise HTTPException(401, "Unauthorized")


router = APIRouter(prefix="/internal/risk", dependencies=[Depends(trusted_risk)])


@router.get("/customers/{customer_id}/evidence")
def evidence(
    customer_id: UUID,
    session: SessionDependency,
    response: Response,
    start: AwareDatetime,
    end: AwareDatetime,
    currency: Annotated[str, Query(pattern="^[A-Z]{3}$")],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    if session is None:
        raise HTTPException(503, "Persistence unavailable")
    try:
        return ReadRiskEvidence(SQLAlchemyRiskEvidenceQuery(session)).execute(
            customer_id, currency, start, end, limit, offset
        )
    except ValueError:
        raise HTTPException(422, "Invalid evidence window") from None
