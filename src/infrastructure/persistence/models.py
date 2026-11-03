"""Persistence schema only; business operations stay in the domain."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain.account.enums import AccountProductType, AccountStatus
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType


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


class TransactionORM(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_transactions"),
        UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
        CheckConstraint(
            "amount > 0 AND amount NOT IN "
            "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_transactions_amount",
        ),
        CheckConstraint(
            "(status NOT IN ('POSTED', 'REVERSED') OR posted_at IS NOT NULL) AND "
            "(status NOT IN ('PENDING', 'REJECTED') OR posted_at IS NULL)",
            name="ck_transactions_posted_at",
        ),
        CheckConstraint(
            "reversal_of_id IS NULL OR reversal_of_id <> id", name="ck_transactions_reversal_of_id"
        ),
        CheckConstraint("currency COLLATE \"C\" ~ '^[A-Z]{3}$'", name="ck_transactions_currency"),
        {"schema": "banking"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(
            TransactionType,
            length=30,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_transactions_transaction_type",
        )
    )
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(
            TransactionStatus,
            length=20,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_transactions_status",
        ),
        server_default=TransactionStatus.PENDING.value,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(CHAR(3))
    description: Mapped[str | None] = mapped_column(Text)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    reversal_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("banking.transactions.id", name="fk_transactions_reversal_of_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountMovementORM(Base):
    __tablename__ = "account_movements"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_account_movements"),
        CheckConstraint(
            "amount > 0 AND amount NOT IN "
            "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_movements_amount",
        ),
        CheckConstraint(
            "balance_after NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_movements_balance_after",
        ),
        {"schema": "banking"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("banking.transactions.id", name="fk_account_movements_transaction_id")
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("banking.accounts.id", name="fk_account_movements_account_id")
    )
    direction: Mapped[MovementDirection] = mapped_column(
        Enum(
            MovementDirection,
            length=10,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_account_movements_direction",
        )
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    category: Mapped[str | None] = mapped_column(String(50))
    counterparty_account: Mapped[str | None] = mapped_column(String(50))
    counterparty_bank: Mapped[str | None] = mapped_column(String(20))
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index(
    "ix_banking_transactions_status_created_at",
    TransactionORM.status,
    TransactionORM.created_at.desc(),
)
Index(
    "ix_banking_account_movements_account_booked_at_id",
    AccountMovementORM.account_id,
    AccountMovementORM.booked_at.desc(),
    AccountMovementORM.id,
)
Index("ix_banking_account_movements_transaction_id", AccountMovementORM.transaction_id)
