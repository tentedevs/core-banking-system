from typing import Annotated
from uuid import UUID

from auth_client import CurrentActor
from fastapi import APIRouter, Depends, HTTPException, Response

from api.authentication import get_current_actor
from api.dependencies import (
    SessionDependency,
    get_get_account,
    get_get_account_balance,
    get_get_transaction,
    get_list_account_movements,
    get_list_accounts,
)
from api.routers.transactions import Limit, Offset
from api.schemas.account import AccountListResponse, AccountPagination, AccountResponse
from api.schemas.customer_banking import (
    CustomerMovementListResponse,
    CustomerMovementResponse,
    CustomerTransactionDetailResponse,
    CustomerTransactionListResponse,
    CustomerTransactionResponse,
)
from api.schemas.transaction import BalanceResponse
from application.account_access_policy import AccountAccessPolicy
from application.account_messages import GetAccountQuery, ListAccountsQuery
from application.transaction_messages import (
    GetAccountBalanceQuery,
    GetTransactionQuery,
    ListAccountMovementsQuery,
    ListTransactionsQuery,
)
from application.use_cases.get_account import GetAccount
from application.use_cases.get_account_balance import GetAccountBalance
from application.use_cases.get_transaction import GetTransaction, TransactionNotFound
from application.use_cases.list_account_movements import ListAccountMovements
from application.use_cases.list_accounts import ListAccounts
from application.use_cases.list_customer_transactions import ListCustomerTransactions
from domain.transaction.enums import TransactionStatus, TransactionType
from infrastructure.persistence.repositories.account_movement_repository import (
    SQLAlchemyAccountMovementRepository,
)
from infrastructure.persistence.repositories.account_repository import SQLAlchemyAccountRepository
from infrastructure.persistence.repositories.actor_customer_link_repository import (
    SQLAlchemyActorCustomerLinkRepository,
)
from infrastructure.persistence.repositories.transaction_repository import (
    SQLAlchemyTransactionRepository,
)

router = APIRouter(prefix="/me", tags=["Customer banking"])


class CustomerReadContext:
    def __init__(
        self,
        actor: CurrentActor,
        policy: AccountAccessPolicy,
        transactions: SQLAlchemyTransactionRepository,
        movements: SQLAlchemyAccountMovementRepository,
    ) -> None:
        self.actor = actor
        self.policy = policy
        self.customer_id = policy.require_customer_link(actor)
        self.transactions = transactions
        self.movements = movements


def get_customer_reads(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    session: SessionDependency,
    response: Response,
) -> CustomerReadContext:
    AccountAccessPolicy.require_customer_actor(actor)
    if session is None:
        raise HTTPException(status_code=503, detail="Identity persistence unavailable")
    transactions = SQLAlchemyTransactionRepository(session)
    movements = SQLAlchemyAccountMovementRepository(session)
    policy = AccountAccessPolicy(
        SQLAlchemyActorCustomerLinkRepository(session),
        SQLAlchemyAccountRepository(session),
        transactions,
    )
    response.headers["Cache-Control"] = "no-store"
    return CustomerReadContext(actor, policy, transactions, movements)


Context = Annotated[CustomerReadContext, Depends(get_customer_reads)]


@router.get("/accounts", response_model=AccountListResponse)
def accounts(
    context: Context,
    use_case: Annotated[ListAccounts, Depends(get_list_accounts)],
    limit: Limit = 50,
    offset: Offset = 0,
) -> AccountListResponse:
    items, total = use_case.execute_with_total(
        ListAccountsQuery(context.customer_id, limit, offset)
    )
    return AccountListResponse(
        items=[AccountResponse.model_validate(item) for item in items],
        pagination=AccountPagination.from_total(limit, offset, total),
    )


@router.get("/accounts/{account_id}", response_model=AccountResponse)
def account(
    account_id: UUID, context: Context, use_case: Annotated[GetAccount, Depends(get_get_account)]
) -> AccountResponse:
    context.policy.require_account_owner(context.actor, account_id)
    return AccountResponse.model_validate(use_case.execute(GetAccountQuery(account_id)))


@router.get("/accounts/{account_id}/balance", response_model=BalanceResponse)
def balance(
    account_id: UUID,
    context: Context,
    use_case: Annotated[GetAccountBalance, Depends(get_get_account_balance)],
) -> BalanceResponse:
    context.policy.require_account_owner(context.actor, account_id)
    return BalanceResponse.model_validate(use_case.execute(GetAccountBalanceQuery(account_id)))


@router.get("/accounts/{account_id}/movements", response_model=CustomerMovementListResponse)
def movements(
    account_id: UUID,
    context: Context,
    use_case: Annotated[ListAccountMovements, Depends(get_list_account_movements)],
    limit: Limit = 50,
    offset: Offset = 0,
) -> CustomerMovementListResponse:
    context.policy.require_account_owner(context.actor, account_id)
    items, total = use_case.execute_with_total(ListAccountMovementsQuery(account_id, limit, offset))
    return CustomerMovementListResponse(
        items=[CustomerMovementResponse.model_validate(item) for item in items],
        pagination=AccountPagination.from_total(limit, offset, total),
    )


@router.get("/transactions", response_model=CustomerTransactionListResponse)
def transactions(
    context: Context,
    limit: Limit = 50,
    offset: Offset = 0,
    transaction_type: TransactionType | None = None,
    status: TransactionStatus | None = None,
) -> CustomerTransactionListResponse:
    items, total = ListCustomerTransactions(context.transactions).execute_with_total(
        context.customer_id, ListTransactionsQuery(limit, offset, transaction_type, status)
    )
    return CustomerTransactionListResponse(
        items=[CustomerTransactionResponse.model_validate(item) for item in items],
        pagination=AccountPagination.from_total(limit, offset, total),
    )


@router.get("/transactions/{transaction_id}", response_model=CustomerTransactionDetailResponse)
def transaction(
    transaction_id: UUID,
    context: Context,
    use_case: Annotated[GetTransaction, Depends(get_get_transaction)],
    limit: Limit = 50,
    offset: Offset = 0,
) -> CustomerTransactionDetailResponse:
    if not context.policy.can_view_transaction(context.actor, transaction_id):
        raise TransactionNotFound("Transaction not found")
    item = use_case.execute(GetTransactionQuery(transaction_id))
    rows = context.movements.list_by_transaction(
        transaction_id, limit, offset, customer_id=context.customer_id
    )
    total = context.movements.count_by_transaction(transaction_id, customer_id=context.customer_id)
    return CustomerTransactionDetailResponse(
        **CustomerTransactionResponse.model_validate(item).model_dump(),
        movements=CustomerMovementListResponse(
            items=[CustomerMovementResponse.model_validate(row) for row in rows],
            pagination=AccountPagination.from_total(limit, offset, total),
        ),
    )
