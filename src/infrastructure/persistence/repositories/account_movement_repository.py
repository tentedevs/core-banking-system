from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.transaction.entities import AccountMovement
from infrastructure.persistence.mappers import account_movement_mapper
from infrastructure.persistence.models import AccountMovementORM
from infrastructure.persistence.repositories.account_repository import SQLAlchemyAccountRepository


class SQLAlchemyAccountMovementRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, movement: AccountMovement) -> None:
        self.session.add(account_movement_mapper.to_orm(movement))
        self.session.flush()

    def list_by_account(
        self, account_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AccountMovement]:
        SQLAlchemyAccountRepository._validate_pagination(limit, offset)
        query = (
            select(AccountMovementORM)
            .where(AccountMovementORM.account_id == account_id)
            .order_by(AccountMovementORM.booked_at.desc(), AccountMovementORM.id)
            .limit(limit)
            .offset(offset)
        )
        return [account_movement_mapper.to_domain(row) for row in self.session.scalars(query)]

    def count_by_account(self, account_id: UUID) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(AccountMovementORM)
                .where(AccountMovementORM.account_id == account_id)
            )
            or 0
        )

    def list_by_transaction(
        self, transaction_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AccountMovement]:
        SQLAlchemyAccountRepository._validate_pagination(limit, offset)
        query = (
            select(AccountMovementORM)
            .where(AccountMovementORM.transaction_id == transaction_id)
            .order_by(AccountMovementORM.booked_at.desc(), AccountMovementORM.id)
            .limit(limit)
            .offset(offset)
        )
        return [account_movement_mapper.to_domain(row) for row in self.session.scalars(query)]

    def count_by_transaction(self, transaction_id: UUID) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(AccountMovementORM)
                .where(AccountMovementORM.transaction_id == transaction_id)
            )
            or 0
        )
