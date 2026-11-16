import hashlib
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from domain.transaction.entities import BankingTransaction
from domain.transaction.enums import TransactionStatus, TransactionType
from infrastructure.persistence.mappers import transaction_mapper
from infrastructure.persistence.models import (
    AccountMovementORM,
    AccountORM,
    TransactionORM,
    TransactionRequestORM,
)
from infrastructure.persistence.repositories.account_repository import SQLAlchemyAccountRepository
from ports.transaction_repository import IdempotencyRecord, TransactionPersistenceConflict


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

    def lock_idempotency_key(self, key: str) -> None:
        # Stable across processes; collisions serialize unrelated keys harmlessly.
        # Transaction-scoped locks also cover the absence of a request row.
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    def get_request(self, key: str) -> IdempotencyRecord | None:
        row = self.session.get(TransactionRequestORM, key)
        return IdempotencyRecord(row.fingerprint, row.transaction_id) if row is not None else None

    def record_request(self, key: str, record: IdempotencyRecord) -> None:
        self.session.add(
            TransactionRequestORM(
                idempotency_key=key,
                fingerprint=record.fingerprint,
                transaction_id=record.transaction_id,
            )
        )
        self.session.flush()

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

    @staticmethod
    def _customer_transaction_ids(customer_id: UUID) -> Select[UUID]:
        return (
            select(AccountMovementORM.transaction_id)
            .join(AccountORM, AccountORM.id == AccountMovementORM.account_id)
            .where(AccountORM.customer_id == customer_id)
        )

    def list_by_customer(
        self,
        customer_id: UUID,
        limit: int = 50,
        offset: int = 0,
        *,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
    ) -> list[BankingTransaction]:
        SQLAlchemyAccountRepository._validate_pagination(limit, offset)
        query = select(TransactionORM).where(
            TransactionORM.id.in_(self._customer_transaction_ids(customer_id))
        )
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

    def count_by_customer(
        self,
        customer_id: UUID,
        *,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(TransactionORM)
            .where(TransactionORM.id.in_(self._customer_transaction_ids(customer_id)))
        )
        if transaction_type is not None:
            query = query.where(TransactionORM.transaction_type == transaction_type)
        if status is not None:
            query = query.where(TransactionORM.status == status)
        return self.session.scalar(query) or 0

    def has_customer_movement(self, transaction_id: UUID, customer_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(TransactionORM.id).where(
                    TransactionORM.id == transaction_id,
                    TransactionORM.id.in_(self._customer_transaction_ids(customer_id)),
                )
            )
            is not None
        )
