import hashlib
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from infrastructure.persistence.models import CustomerAccountOpeningORM
from ports.account_opening_repository import CustomerAccountOpening


class SQLAlchemyAccountOpeningRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_customer(self, customer_id: UUID) -> None:
        key = int.from_bytes(
            hashlib.sha256(f"account-opening:{customer_id}".encode()).digest()[:8],
            signed=True,
        )
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def get(self, customer_id: UUID) -> CustomerAccountOpening | None:
        row = self.session.get(CustomerAccountOpeningORM, customer_id)
        return (
            CustomerAccountOpening(row.customer_id, row.account_id, row.currency) if row else None
        )

    def add(self, opening: CustomerAccountOpening) -> None:
        self.session.add(
            CustomerAccountOpeningORM(
                customer_id=opening.customer_id,
                account_id=opening.account_id,
                currency=opening.currency,
            )
        )
        self.session.flush()
