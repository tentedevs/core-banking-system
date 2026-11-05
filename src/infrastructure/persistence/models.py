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
from domain.account_balance.enums import BalanceInitializationPolicy
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType


class Base(DeclarativeBase):
    pass


class TransactionRequestORM(Base):
    """Immutable idempotency receipt, committed with its financial operation."""

    __tablename__ = "transaction_requests"
    __table_args__ = (
        PrimaryKeyConstraint("idempotency_key", name="pk_transaction_requests"),
        UniqueConstraint("transaction_id", name="uq_transaction_requests_transaction_id"),
        CheckConstraint("idempotency_key ~ '[^[:space:]]'", name="ck_transaction_requests_key"),
        CheckConstraint(
            "fingerprint COLLATE \"C\" ~ '^[0-9a-f]{64}$'",
            name="ck_transaction_requests_fingerprint",
        ),
        {"schema": "banking"},
    )

    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("banking.transactions.id", name="fk_transaction_requests_transaction_id"),
        nullable=False,
    )


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


class AccountBalanceORM(Base):
    __tablename__ = "account_balances"
    __table_args__ = (
        PrimaryKeyConstraint("account_id", name="pk_account_balances"),
        CheckConstraint("available_balance = booked_balance", name="ck_account_balances_available"),
        CheckConstraint(
            "booked_balance NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_balances_booked",
        ),
        CheckConstraint(
            "available_balance NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_balances_finite_available",
        ),
        {"schema": "banking"},
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("banking.accounts.id", name="fk_account_balances_account_id"), primary_key=True
    )
    booked_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    available_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BalanceOpeningORM(Base):
    __tablename__ = "account_balance_openings"
    __table_args__ = (
        PrimaryKeyConstraint("account_id", name="pk_account_balance_openings"),
        CheckConstraint(
            "opening_balance NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_balance_openings_finite",
        ),
        CheckConstraint(
            "policy = 'HISTORICAL' OR opening_balance >= 0",
            name="ck_account_balance_openings_negative_policy",
        ),
        {"schema": "banking"},
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "banking.account_balances.account_id", name="fk_account_balance_openings_balance"
        ),
        primary_key=True,
    )
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    policy: Mapped[BalanceInitializationPolicy] = mapped_column(
        Enum(
            BalanceInitializationPolicy,
            length=20,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="ck_account_balance_openings_policy",
        )
    )
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActorCustomerLinkORM(Base):
    __tablename__ = "actor_customer_links"
    __table_args__ = (
        PrimaryKeyConstraint("actor_id", name="pk_actor_customer_links"),
        Index("ix_actor_customer_links_customer_id", "customer_id"),
        {"schema": "banking"},
    )
    actor_id: Mapped[UUID] = mapped_column()
    customer_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerOnboardingORM(Base):
    __tablename__ = "customer_onboardings"
    __table_args__ = (
        PrimaryKeyConstraint("actor_id", name="pk_customer_onboardings"),
        UniqueConstraint("customer_id", name="uq_customer_onboardings_customer_id"),
        UniqueConstraint("account_id", name="uq_customer_onboardings_account_id"),
        CheckConstraint(
            "fingerprint COLLATE \"C\" ~ '^[0-9a-f]{64}$'",
            name="ck_customer_onboardings_fingerprint",
        ),
        {"schema": "banking"},
    )
    actor_id: Mapped[UUID] = mapped_column()
    customer_id: Mapped[UUID] = mapped_column()
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("banking.accounts.id", name="fk_customer_onboardings_account"), nullable=True
    )
