from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from api.dependencies import (
    get_create_deposit,
    get_create_transfer,
    get_create_withdrawal,
    get_get_account_balance,
    get_get_transaction,
    get_list_account_movements,
    get_list_transaction_movements,
    get_list_transactions,
)
from api.schemas.account import AccountPagination, ErrorResponse
from api.schemas.transaction import (
    BalanceResponse,
    DepositRequest,
    MovementListResponse,
    MovementResponse,
    TransactionListResponse,
    TransactionResponse,
    TransferRequest,
    WithdrawalRequest,
)
from application.transaction_messages import (
    CreateDepositCommand,
    CreateTransferCommand,
    CreateWithdrawalCommand,
    GetAccountBalanceQuery,
    GetTransactionQuery,
    ListAccountMovementsQuery,
    ListTransactionMovementsQuery,
    ListTransactionsQuery,
)
from application.use_cases.create_deposit import CreateDeposit
from application.use_cases.create_transfer import CreateTransfer
from application.use_cases.create_withdrawal import CreateWithdrawal
from application.use_cases.get_account_balance import GetAccountBalance
from application.use_cases.get_transaction import GetTransaction
from application.use_cases.list_account_movements import ListAccountMovements
from application.use_cases.list_transaction_movements import ListTransactionMovements
from application.use_cases.list_transactions import ListTransactions
from domain.transaction.enums import TransactionStatus, TransactionType

router = APIRouter(
    tags=["Transactions"],
    responses={
        404: {"model": ErrorResponse, "description": "Account or transaction not found"},
        409: {
            "model": ErrorResponse,
            "description": (
                "Insufficient funds, inactive account, idempotency conflict or "
                "uninitialized balance"
            ),
        },
        422: {
            "model": ErrorResponse,
            "description": "Invalid request, amount or incompatible currency",
        },
        500: {"model": ErrorResponse, "description": "Unexpected internal failure"},
        503: {"model": ErrorResponse, "description": "Persistence unavailable"},
    },
)

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=100,
        pattern=r"\S",
        description=(
            "Required stable key (1–100 characters). Identical retries return "
            "the original transaction; different payloads conflict. Preserve after timeouts."
        ),
    ),
]
Limit = Annotated[int, Query(ge=1, le=100, description="Maximum items, 1–100")]
Offset = Annotated[int, Query(ge=0, description="Number of matching items to skip")]


@router.post("/transactions/deposits", status_code=201, response_model=TransactionResponse)
def create_deposit(
    payload: DepositRequest,
    idempotency_key: IdempotencyKey,
    use_case: Annotated[CreateDeposit, Depends(get_create_deposit)],
) -> TransactionResponse:
    """Simulated cash inflow: atomically post one CREDIT and increase the projection.

    This is a simulated external cash deposit, with no source CBS account or
    external settlement. All effects commit together. Idempotent retries return
    the original POSTED transaction with the same 201 response status.
    """
    result = use_case.execute(
        CreateDepositCommand(**payload.model_dump(), idempotency_key=idempotency_key)
    )
    return TransactionResponse.model_validate(result)


@router.post("/transactions/withdrawals", status_code=201, response_model=TransactionResponse)
def create_withdrawal(
    payload: WithdrawalRequest,
    idempotency_key: IdempotencyKey,
    use_case: Annotated[CreateWithdrawal, Depends(get_create_withdrawal)],
) -> TransactionResponse:
    """Atomically post one DEBIT and decrease the projection, without overdrafts.

    Insufficient funds return 409 with no persisted monetary effects or REJECTED
    record. All writes share one transaction. Identical retries return the original
    POSTED transaction with 201; a different request with the same key returns 409.
    """
    result = use_case.execute(
        CreateWithdrawalCommand(**payload.model_dump(), idempotency_key=idempotency_key)
    )
    return TransactionResponse.model_validate(result)


@router.post("/transactions/transfers", status_code=201, response_model=TransactionResponse)
def create_transfer(
    payload: TransferRequest,
    idempotency_key: IdempotencyKey,
    use_case: Annotated[CreateTransfer, Depends(get_create_transfer)],
) -> TransactionResponse:
    """Atomically debit source and credit destination, recording two movements.

    Both accounts must be ACTIVE, distinct and match the requested currency.
    Ordered row locks prevent concurrent overspending; failure rolls back both
    sides. Idempotent retries return the original POSTED transaction with 201.
    This is an internal CBS transfer; no ledger or external payment is involved.
    """
    result = use_case.execute(
        CreateTransferCommand(**payload.model_dump(), idempotency_key=idempotency_key)
    )
    return TransactionResponse.model_validate(result)


@router.get("/transactions", response_model=TransactionListResponse)
def list_transactions(
    use_case: Annotated[ListTransactions, Depends(get_list_transactions)],
    limit: Limit = 50,
    offset: Offset = 0,
    transaction_type: TransactionType | None = None,
    status: TransactionStatus | None = None,
) -> TransactionListResponse:
    """Filter by type/status, ordered by created_at DESC then UUID ASC, with matching totals."""
    items, total = use_case.execute_with_total(
        ListTransactionsQuery(limit, offset, transaction_type, status)
    )
    return TransactionListResponse(
        items=[TransactionResponse.model_validate(item) for item in items],
        pagination=AccountPagination.from_total(limit, offset, total),
    )


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: UUID,
    use_case: Annotated[GetTransaction, Depends(get_get_transaction)],
) -> TransactionResponse:
    """Retrieve an immutable financial snapshot, including its current lifecycle status."""
    return TransactionResponse.model_validate(use_case.execute(GetTransactionQuery(transaction_id)))


@router.get("/accounts/{account_id}/movements", response_model=MovementListResponse)
def list_account_movements(
    account_id: UUID,
    use_case: Annotated[ListAccountMovements, Depends(get_list_account_movements)],
    limit: Limit = 50,
    offset: Offset = 0,
) -> MovementListResponse:
    """List account movements ordered by booked_at DESC then UUID ASC, with matching totals.

    balance_after is a historical booking snapshot; use /balance for current values.
    """
    items, total = use_case.execute_with_total(ListAccountMovementsQuery(account_id, limit, offset))
    return MovementListResponse(
        items=[MovementResponse.model_validate(item) for item in items],
        pagination=AccountPagination.from_total(limit, offset, total),
    )


@router.get("/accounts/{account_id}/balance", response_model=BalanceResponse)
def get_account_balance(
    account_id: UUID,
    use_case: Annotated[GetAccountBalance, Depends(get_get_account_balance)],
) -> BalanceResponse:
    """Read the current AccountBalance projection without recomputing movement history.

    booked_balance and available_balance currently match (no reservations).
    A historical account without an initialized projection returns 409; reads
    never initialize or alter balances. Historical negative balances may exist;
    live monetary operations cannot create an overdraft.
    """
    return BalanceResponse.model_validate(use_case.execute(GetAccountBalanceQuery(account_id)))


@router.get("/transactions/{transaction_id}/movements", response_model=MovementListResponse)
def list_transaction_movements(
    transaction_id: UUID,
    use_case: Annotated[ListTransactionMovements, Depends(get_list_transaction_movements)],
    limit: Limit = 50,
    offset: Offset = 0,
) -> MovementListResponse:
    """Read a transaction's movements, including both sides of an internal transfer.

    Ordered by booked_at DESC, UUID ASC. A known transaction without movements
    returns an empty page; an unknown transaction returns 404. No monetary writes.
    """
    items, total = use_case.execute_with_total(
        ListTransactionMovementsQuery(transaction_id, limit, offset)
    )
    return MovementListResponse(
        items=[MovementResponse.model_validate(item) for item in items],
        pagination=AccountPagination.from_total(limit, offset, total),
    )
