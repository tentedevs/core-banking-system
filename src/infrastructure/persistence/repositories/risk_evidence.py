import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from domain.transaction.enums import TransactionStatus
from infrastructure.persistence.models import AccountMovementORM as Movement
from infrastructure.persistence.models import AccountORM as Account
from infrastructure.persistence.models import TransactionORM as Transaction


class SQLAlchemyRiskEvidenceQuery:
    def __init__(self, session: Session) -> None:
        self.session = session

    def page(
        self,
        customer_id: UUID,
        currency: str,
        start: datetime,
        end: datetime,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        other_move = aliased(Movement)
        other_account = aliased(Account)
        owned_transfer = exists(
            select(other_move.id)
            .join(other_account, other_account.id == other_move.account_id)
            .where(
                other_move.transaction_id == Movement.transaction_id,
                other_move.account_id != Movement.account_id,
                other_account.customer_id == customer_id,
            )
        )
        rows = self.session.execute(
            select(Movement, Transaction, owned_transfer)
            .select_from(Movement)
            .join(Account, Account.id == Movement.account_id)
            .join(Transaction, Transaction.id == Movement.transaction_id)
            .where(
                Account.customer_id == customer_id,
                Account.currency == currency,
                Transaction.currency == currency,
                Movement.booked_at >= start,
                Movement.booked_at < end,
                Transaction.status.in_([TransactionStatus.POSTED, TransactionStatus.REVERSED]),
            )
            .order_by(Movement.booked_at, Movement.id)
            .limit(10001)
        ).all()
        if len(rows) > 10000:
            raise ValueError("Evidence window exceeds the supported limit")
        items = [
            {
                "id": str(m.id),
                "account_id": str(m.account_id),
                "transaction_id": str(m.transaction_id),
                "amount": str(m.amount),
                "direction": m.direction.value,
                "category": m.category,
                "booked_at": m.booked_at.isoformat(),
                "own_transfer": own,
                "status": t.status.value,
                "reversal_of_id": str(t.reversal_of_id) if t.reversal_of_id else None,
            }
            for m, t, own in rows
        ]
        payload = {
            "customer_id": str(customer_id),
            "currency": currency,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "items": items,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return {
            **payload,
            "items": items[offset : offset + limit],
            "offset": offset,
            "has_more": offset + limit < len(items),
            "reference": "sha256:" + digest,
        }
