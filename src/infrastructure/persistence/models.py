"""Persistence schema only; business operations stay in the domain."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain.account.enums import AccountProductType, AccountStatus


class Base(DeclarativeBase):
    pass


class AccountORM(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_accounts"),
        UniqueConstraint("account_number", name="uq_accounts_account_number"),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at", name="ck_accounts_lifecycle_dates"
        ),
        CheckConstraint(
            "(status = 'CLOSED') = (closed_at IS NOT NULL)", name="ck_accounts_closed_at"
        ),
        CheckConstraint("account_number ~ '[^[:space:]]'", name="ck_accounts_account_number"),
        CheckConstraint("currency COLLATE \"C\" ~ '^[A-Z]{3}$'", name="ck_accounts_currency"),
        {"schema": "banking"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(index=True)
    account_number: Mapped[str] = mapped_column(String(34))
    product_type: Mapped[AccountProductType] = mapped_column(
        Enum(
            AccountProductType,
            length=30,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_accounts_product_type",
        ),
        server_default=AccountProductType.SAVINGS_ACCOUNT.value,
    )
    currency: Mapped[str] = mapped_column(CHAR(3))
    status: Mapped[AccountStatus] = mapped_column(
        Enum(
            AccountStatus,
            length=20,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_accounts_status",
        ),
        server_default=AccountStatus.ACTIVE.value,
    )
    opened_at: Mapped[date] = mapped_column(Date)
    closed_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
