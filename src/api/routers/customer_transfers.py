from typing import Annotated

from auth_client import CurrentActor
from fastapi import APIRouter, Depends, Request, Response

from api.authentication import get_current_actor, validate_banking_request_origin
from api.dependencies import AccountWorkDependency
from api.routers.transactions import IdempotencyKey
from api.schemas.customer_banking import CustomerTransactionResponse
from api.schemas.transaction import TransferRequest
from application.account_access_policy import AccountAccessPolicy
from application.transaction_messages import CreateTransferCommand
from application.use_cases.create_customer_transfer import CreateCustomerTransfer

router = APIRouter(prefix="/me", tags=["Customer banking"])


def transfer_actor(
    request: Request, actor: Annotated[CurrentActor, Depends(get_current_actor)]
) -> CurrentActor:
    AccountAccessPolicy.require_customer_actor(actor)
    validate_banking_request_origin(request)
    return actor


@router.post(
    "/transfers",
    status_code=201,
    response_model=CustomerTransactionResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Customer access, link or trusted origin required"},
        404: {"description": "Account not found"},
        409: {"description": "Funds, state or idempotency conflict"},
        503: {"description": "Service unavailable"},
    },
)
def transfer(
    actor: Annotated[CurrentActor, Depends(transfer_actor)],
    payload: TransferRequest,
    idempotency_key: IdempotencyKey,
    work: AccountWorkDependency,
    response: Response,
) -> CustomerTransactionResponse:
    transaction = CreateCustomerTransfer(work).execute(
        actor, CreateTransferCommand(**payload.model_dump(), idempotency_key=idempotency_key)
    )
    response.headers["Cache-Control"] = "no-store"
    return CustomerTransactionResponse.model_validate(transaction)
