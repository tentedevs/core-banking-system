from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.transaction.entities import BankingTransaction
from domain.transaction.enums import TransactionStatus, TransactionType
from infrastructure.persistence.mappers import transaction_mapper
from infrastructure.persistence.models import TransactionORM
from infrastructure.persistence.repositories.account_repository import SQLAlchemyAccountRepository
from ports.transaction_repository import TransactionPersistenceConflict


class SQLAlchemyTransactionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, transaction: BankingTransaction) -> None:
        self.session.add(transaction_mapper.to_orm(transaction))
        self.session.flush()

    def post(self, transaction: BankingTransaction) -> None:
        values = transaction_mapper.to_orm(transaction)
        row = self.session.get(TransactionORM, transaction.id)
        if (
            row is None
            or row.status != TransactionStatus.PENDING
            or values.status != TransactionStatus.POSTED
        ):
            raise TransactionPersistenceConflict(
                "Only an existing PENDING transaction can be posted"
            )
        # Financial fields and references are never overwritten by an update.
        row.status = values.status
        row.posted_at = values.posted_at
        self.session.flush()

    def get_by_id(self, transaction_id: UUID) -> BankingTransaction | None:
        row = self.session.get(TransactionORM, transaction_id)
        return transaction_mapper.to_domain(row) if row is not None else None

    def get_by_idempotency_key(self, key: str) -> BankingTransaction | None:
        row = self.session.scalar(
            select(TransactionORM).where(TransactionORM.idempotency_key == key)
        )
        return transaction_mapper.to_domain(row) if row is not None else None

    def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
    ) -> list[BankingTransaction]:
        SQLAlchemyAccountRepository._validate_pagination(limit, offset)
        query = select(TransactionORM)
        if transaction_type is not None:
            query = query.where(TransactionORM.transaction_type == transaction_type)
        if status is not None:
            query = query.where(TransactionORM.status == status)
        query = (
            query.order_by(TransactionORM.created_at.desc(), TransactionORM.id)
            .limit(limit)
            .offset(offset)
        )
        return [transaction_mapper.to_domain(row) for row in self.session.scalars(query)]

    def count(
        self,
        *,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
    ) -> int:
        query = select(func.count()).select_from(TransactionORM)
        if transaction_type is not None:
            query = query.where(TransactionORM.transaction_type == transaction_type)
        if status is not None:
            query = query.where(TransactionORM.status == status)
        return self.session.scalar(query) or 0
