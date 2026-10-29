"""Create banking.accounts for the SAVINGS_ACCOUNT product.

Revision ID: 0001_create_accounts
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_create_accounts"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema("banking", if_not_exists=True))
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("account_number", sa.String(34), nullable=False),
        sa.Column("product_type", sa.String(30), nullable=False, server_default="SAVINGS_ACCOUNT"),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("opened_at", sa.Date(), nullable=False),
        sa.Column("closed_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        sa.UniqueConstraint("account_number", name="uq_accounts_account_number"),
        sa.CheckConstraint("product_type = 'SAVINGS_ACCOUNT'", name="ck_accounts_product_type"),
        sa.CheckConstraint("status IN ('ACTIVE', 'BLOCKED', 'CLOSED')", name="ck_accounts_status"),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at", name="ck_accounts_lifecycle_dates"
        ),
        sa.CheckConstraint(
            "(status = 'CLOSED') = (closed_at IS NOT NULL)", name="ck_accounts_closed_at"
        ),
        sa.CheckConstraint("account_number ~ '[^[:space:]]'", name="ck_accounts_account_number"),
        sa.CheckConstraint("currency COLLATE \"C\" ~ '^[A-Z]{3}$'", name="ck_accounts_currency"),
        schema="banking",
    )
    op.create_index(
        "ix_banking_accounts_customer_id", "accounts", ["customer_id"], schema="banking"
    )


def downgrade() -> None:
    op.drop_index("ix_banking_accounts_customer_id", table_name="accounts", schema="banking")
    op.drop_table("accounts", schema="banking")
    # The schema may predate this migration or contain other modules. Preserve it.
