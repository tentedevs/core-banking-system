import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType
from domain.transaction.exceptions import InvalidAccountMovementData, InvalidTransactionData


def _require_uuid(value: object, field: str, error: type[ValueError]) -> None:
    if not isinstance(value, UUID):
        raise error(f"{field} must be a UUID")


def _require_amount(value: object, field: str, error: type[ValueError]) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise error(f"{field} must be a finite, positive Decimal")


def _require_datetime(value: object, field: str, error: type[ValueError]) -> None:
    if not isinstance(value, datetime):
        raise error(f"{field} must be a datetime")


def _require_optional_text(value: object, field: str, error: type[ValueError]) -> None:
    if value is not None and not isinstance(value, str):
        raise error(f"{field} must be a string or None")


@dataclass(frozen=True)
class BankingTransaction:
    """Immutable operation snapshot, separate from its posted account movements.

    Use create() for a new PENDING operation. Direct construction validates and
    preserves historical state; it is not a posting operation. Posting requires
    application-level balance coordination. There is no post/reverse API.

    Currency follows Accounts: exactly three uppercase ASCII letters, with ISO
    4217 membership not yet verified. Monetary precision is preserved unchanged.
    """

    id: UUID
    transaction_type: TransactionType
    status: TransactionStatus
    amount: Decimal
    currency: str
    effective_at: datetime
    created_at: datetime
    description: str | None = None
    posted_at: datetime | None = None
    idempotency_key: str | None = None
    reversal_of_id: UUID | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        _require_uuid(self.id, "id", InvalidTransactionData)
        if not isinstance(self.transaction_type, TransactionType):
            raise InvalidTransactionData("transaction_type must be a TransactionType")
        if not isinstance(self.status, TransactionStatus):
            raise InvalidTransactionData("status must be a TransactionStatus")
        _require_amount(self.amount, "amount", InvalidTransactionData)
        if not isinstance(self.currency, str) or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise InvalidTransactionData("currency must be a three-letter uppercase code")
        for field in ("effective_at", "created_at"):
            _require_datetime(getattr(self, field), field, InvalidTransactionData)
        if self.posted_at is not None:
            _require_datetime(self.posted_at, "posted_at", InvalidTransactionData)
        if self.status in (TransactionStatus.POSTED, TransactionStatus.REVERSED):
            if self.posted_at is None:
                raise InvalidTransactionData("POSTED and REVERSED transactions require posted_at")
        elif self.posted_at is not None:
            raise InvalidTransactionData(
                "PENDING and REJECTED transactions must not have posted_at"
            )
        for field in ("description", "idempotency_key"):
            _require_optional_text(getattr(self, field), field, InvalidTransactionData)
        if self.reversal_of_id is not None:
            _require_uuid(self.reversal_of_id, "reversal_of_id", InvalidTransactionData)
            if self.reversal_of_id == self.id:
                raise InvalidTransactionData(
                    "reversal_of_id cannot reference the transaction itself"
                )

    @classmethod
    def create(
        cls,
        *,
        transaction_type: TransactionType,
        amount: Decimal,
        currency: str,
        effective_at: datetime,
        description: str | None = None,
        idempotency_key: str | None = None,
        reversal_of_id: UUID | None = None,
    ) -> "BankingTransaction":
        """Create only a PENDING operation; never post or reverse financial effects."""
        return cls(
            id=uuid4(),
            transaction_type=transaction_type,
            status=TransactionStatus.PENDING,
            amount=amount,
            currency=currency,
            effective_at=effective_at,
            created_at=datetime.now(UTC),
            description=description,
            idempotency_key=idempotency_key,
            reversal_of_id=reversal_of_id,
        )


@dataclass(frozen=True)
class AccountMovement:
    """Immutable account-side effect; never reads or updates an account balance.

    CREDIT enters a customer account; DEBIT leaves it. References and historical
    balance_after are supplied by the caller. Transaction eligibility, account
    existence and posting cardinalities require application-level coordination.
    """

    id: UUID
    transaction_id: UUID
    account_id: UUID
    direction: MovementDirection
    amount: Decimal
    booked_at: datetime
    balance_after: Decimal | None = None
    category: str | None = None
    counterparty_account: str | None = None
    counterparty_bank: str | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for field in ("id", "transaction_id", "account_id"):
            _require_uuid(getattr(self, field), field, InvalidAccountMovementData)
        if not isinstance(self.direction, MovementDirection):
            raise InvalidAccountMovementData("direction must be a MovementDirection")
        _require_amount(self.amount, "amount", InvalidAccountMovementData)
        if self.balance_after is not None and (
            not isinstance(self.balance_after, Decimal) or not self.balance_after.is_finite()
        ):
            raise InvalidAccountMovementData("balance_after must be a finite Decimal or None")
        for field in ("category", "counterparty_account", "counterparty_bank"):
            _require_optional_text(getattr(self, field), field, InvalidAccountMovementData)
        _require_datetime(self.booked_at, "booked_at", InvalidAccountMovementData)

    @classmethod
    def create(
        cls,
        *,
        transaction_id: UUID,
        account_id: UUID,
        direction: MovementDirection,
        amount: Decimal,
        booked_at: datetime,
        balance_after: Decimal | None = None,
        category: str | None = None,
        counterparty_account: str | None = None,
        counterparty_bank: str | None = None,
    ) -> "AccountMovement":
        """Create a validated snapshot; perform no transaction posting or balance update."""
        return cls(
            id=uuid4(),
            transaction_id=transaction_id,
            account_id=account_id,
            direction=direction,
            amount=amount,
            booked_at=booked_at,
            balance_after=balance_after,
            category=category,
            counterparty_account=counterparty_account,
            counterparty_bank=counterparty_bank,
        )
