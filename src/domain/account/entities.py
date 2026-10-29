import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from domain.account.enums import AccountProductType, AccountStatus
from domain.account.exceptions import InvalidAccountData, InvalidAccountStateTransition


@dataclass(frozen=True)
class Account:
    """Immutable account snapshot; retain the result of each transition method.

    Direct construction reconstructs historical state without resetting fields.
    Currency must already be normalized: three uppercase ASCII letters. ISO 4217
    membership is not yet verified because no currency registry is provided.
    """

    id: UUID
    customer_id: UUID
    account_number: str
    product_type: AccountProductType
    currency: str
    status: AccountStatus
    opened_at: date
    created_at: datetime
    updated_at: datetime
    closed_at: date | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for field in ("id", "customer_id"):
            if not isinstance(getattr(self, field), UUID):
                raise InvalidAccountData(f"{field} must be a UUID")
        if not isinstance(self.account_number, str) or not self.account_number.strip():
            raise InvalidAccountData("account_number must be a non-empty string")
        if not isinstance(self.product_type, AccountProductType):
            raise InvalidAccountData("product_type must be an AccountProductType")
        if not isinstance(self.currency, str) or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise InvalidAccountData("currency must be a three-letter uppercase code")
        if not isinstance(self.status, AccountStatus):
            raise InvalidAccountData("status must be an AccountStatus")
        # datetime subclasses date, but opening/closing are calendar dates only.
        if type(self.opened_at) is not date:
            raise InvalidAccountData("opened_at must be a date")
        if self.closed_at is not None:
            if type(self.closed_at) is not date:
                raise InvalidAccountData("closed_at must be a date or None")
            if self.closed_at < self.opened_at:
                raise InvalidAccountData("closed_at cannot precede opened_at")
        if self.status is AccountStatus.CLOSED and self.closed_at is None:
            raise InvalidAccountData("a CLOSED account must have closed_at")
        if self.status is not AccountStatus.CLOSED and self.closed_at is not None:
            raise InvalidAccountData("only a CLOSED account can have closed_at")
        for field in ("created_at", "updated_at"):
            if not isinstance(getattr(self, field), datetime):
                raise InvalidAccountData(f"{field} must be a datetime")

    @classmethod
    def create(
        cls,
        *,
        customer_id: UUID,
        account_number: str,
        product_type: AccountProductType = AccountProductType.SAVINGS_ACCOUNT,
        currency: str,
        opened_at: date,
    ) -> "Account":
        """Create a new ACTIVE account with a generated identity and UTC timestamps."""
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            customer_id=customer_id,
            account_number=account_number,
            product_type=product_type,
            currency=currency,
            status=AccountStatus.ACTIVE,
            opened_at=opened_at,
            created_at=now,
            updated_at=now,
        )

    def block(self) -> "Account":
        """Return a BLOCKED snapshot of an ACTIVE account."""
        if self.status is not AccountStatus.ACTIVE:
            raise InvalidAccountStateTransition(f"cannot block an account in {self.status} status")
        return replace(self, status=AccountStatus.BLOCKED, updated_at=datetime.now(UTC))

    def reactivate(self) -> "Account":
        """Return an ACTIVE snapshot of a BLOCKED account."""
        if self.status is not AccountStatus.BLOCKED:
            raise InvalidAccountStateTransition(
                f"cannot reactivate an account in {self.status} status"
            )
        return replace(self, status=AccountStatus.ACTIVE, updated_at=datetime.now(UTC))
