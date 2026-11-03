from domain.transaction.entities import BankingTransaction
from domain.transaction.enums import TransactionStatus, TransactionType
from infrastructure.persistence.mappers._transaction_validation import (
    require_aware,
    require_loaded,
    require_money,
)
from infrastructure.persistence.models import TransactionORM


def _validate_storage(transaction: BankingTransaction | TransactionORM) -> None:
    require_money(transaction.amount, "amount")
    require_aware(transaction.effective_at, "effective_at")
    require_aware(transaction.created_at, "created_at")
    if transaction.posted_at is not None:
        require_aware(transaction.posted_at, "posted_at")


def to_orm(transaction: BankingTransaction) -> TransactionORM:
    _validate_storage(transaction)
    return TransactionORM(
        id=transaction.id,
        transaction_type=transaction.transaction_type,
        status=transaction.status,
        amount=transaction.amount,
        currency=transaction.currency,
        description=transaction.description,
        effective_at=transaction.effective_at,
        posted_at=transaction.posted_at,
        idempotency_key=transaction.idempotency_key,
        reversal_of_id=transaction.reversal_of_id,
        created_at=transaction.created_at,
    )


def to_domain(transaction: TransactionORM) -> BankingTransaction:
    require_loaded(transaction)
    _validate_storage(transaction)
    return BankingTransaction(
        id=transaction.id,
        transaction_type=TransactionType(transaction.transaction_type),
        status=TransactionStatus(transaction.status),
        amount=transaction.amount,
        currency=transaction.currency,
        description=transaction.description,
        effective_at=transaction.effective_at,
        posted_at=transaction.posted_at,
        idempotency_key=transaction.idempotency_key,
        reversal_of_id=transaction.reversal_of_id,
        created_at=transaction.created_at,
    )
