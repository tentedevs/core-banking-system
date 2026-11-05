import hashlib
from uuid import UUID

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from infrastructure.persistence.models import CustomerOnboardingORM
from ports.customer_onboarding import CustomerOnboarding


class SQLAlchemyCustomerOnboardingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_actor(self, actor_id: UUID) -> None:
        key = int.from_bytes(
            hashlib.sha256(("customer-onboarding:" + str(actor_id)).encode()).digest()[:8],
            signed=True,
        )
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def get(self, actor_id: UUID) -> CustomerOnboarding | None:
        row = self.session.get(CustomerOnboardingORM, actor_id, populate_existing=True)
        return (
            CustomerOnboarding(row.actor_id, row.customer_id, row.fingerprint, row.account_id)
            if row
            else None
        )

    def add(self, request: CustomerOnboarding) -> None:
        self.session.add(
            CustomerOnboardingORM(
                actor_id=request.actor_id,
                customer_id=request.customer_id,
                fingerprint=request.fingerprint,
            )
        )
        self.session.flush()

    def complete(self, actor_id: UUID, account_id: UUID) -> None:
        row = self.session.get(CustomerOnboardingORM, actor_id)
        if row is None:
            raise RuntimeError("Missing onboarding identity")
        row.account_id = account_id
        self.session.flush()

    def discard_rejected(self, actor_id: UUID, customer_id: UUID) -> None:
        self.session.execute(
            delete(CustomerOnboardingORM).where(
                CustomerOnboardingORM.actor_id == actor_id,
                CustomerOnboardingORM.customer_id == customer_id,
                CustomerOnboardingORM.account_id.is_(None),
            )
        )
