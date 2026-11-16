"""Create transactions and account movements without ledger or balances.

Revision ID: 0002_create_transactions
Revises: 0001_create_accounts
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_create_transactions"
down_revision = "0001_create_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"], ["banking.transactions.id"], name="fk_transactions_reversal_of_id"
        ),
        sa.CheckConstraint(
            "transaction_type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER')",
            name="ck_transactions_transaction_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'POSTED', 'REJECTED', 'REVERSED')", name="ck_transactions_status"
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount NOT IN "
            "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_transactions_amount",
        ),
        sa.CheckConstraint(
            "(status NOT IN ('POSTED', 'REVERSED') OR posted_at IS NOT NULL) AND "
            "(status NOT IN ('PENDING', 'REJECTED') OR posted_at IS NULL)",
            name="ck_transactions_posted_at",
        ),
        sa.CheckConstraint(
            "reversal_of_id IS NULL OR reversal_of_id <> id", name="ck_transactions_reversal_of_id"
        ),
        sa.CheckConstraint(
            "currency COLLATE \"C\" ~ '^[A-Z]{3}$'", name="ck_transactions_currency"
        ),
        schema="banking",
    )
    op.create_index(
        "ix_banking_transactions_status_created_at",
        "transactions",
        ["status", sa.text("created_at DESC")],
        schema="banking",
    )
    op.create_table(
        "account_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(18, 2), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("counterparty_account", sa.String(50), nullable=True),
        sa.Column("counterparty_bank", sa.String(20), nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_account_movements"),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["banking.transactions.id"],
            name="fk_account_movements_transaction_id",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["banking.accounts.id"], name="fk_account_movements_account_id"
        ),
        sa.CheckConstraint(
            "direction IN ('CREDIT', 'DEBIT')", name="ck_account_movements_direction"
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount NOT IN "
            "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_movements_amount",
        ),
        sa.CheckConstraint(
            "balance_after NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_movements_balance_after",
        ),
        schema="banking",
    )
    op.create_index(
        "ix_banking_account_movements_account_booked_at_id",
        "account_movements",
        ["account_id", sa.text("booked_at DESC"), "id"],
        schema="banking",
    )
    op.create_index(
        "ix_banking_account_movements_transaction_id",
        "account_movements",
        ["transaction_id"],
        schema="banking",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_banking_account_movements_transaction_id",
        table_name="account_movements",
        schema="banking",
    )
    op.drop_index(
        "ix_banking_account_movements_account_booked_at_id",
        table_name="account_movements",
        schema="banking",
    )
    op.drop_table("account_movements", schema="banking")
    op.drop_index(
        "ix_banking_transactions_status_created_at", table_name="transactions", schema="banking"
    )
    op.drop_table("transactions", schema="banking")
