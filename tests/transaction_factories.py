from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from domain.transaction.entities import AccountMovement, BankingTransaction
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType


def transaction() -> BankingTransaction:
    return BankingTransaction(
        id=uuid4(),
        transaction_type=TransactionType.TRANSFER,
        status=TransactionStatus.POSTED,
        amount=Decimal("123.45"),
        currency="CZK",
        description="Internal transfer",
        effective_at=datetime(2024, 1, 1, 9, 10, 11, 123456, tzinfo=timezone(timedelta(hours=8))),
        posted_at=datetime(2024, 1, 2, tzinfo=UTC),
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        idempotency_key="request-123",
        reversal_of_id=None,
    )


def movement(transaction_id: UUID, account_id: UUID) -> AccountMovement:
    return AccountMovement(
        id=uuid4(),
        transaction_id=transaction_id,
        account_id=account_id,
        direction=MovementDirection.DEBIT,
        amount=Decimal("123.45"),
        balance_after=Decimal("-0.01"),
        category="transfer",
        counterparty_account="000-123",
        counterparty_bank="BANK",
        booked_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
