"""Add account balance projections and explicit opening metadata, without ledger.

Revision ID: 0003_create_account_balances
Revises: 0002_create_transactions
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_create_account_balances"
down_revision = "0002_create_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_balances",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("booked_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("available_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_id", name="pk_account_balances"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["banking.accounts.id"], name="fk_account_balances_account_id"
        ),
        sa.CheckConstraint(
            "available_balance = booked_balance", name="ck_account_balances_available"
        ),
        sa.CheckConstraint(
            "booked_balance NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_balances_booked",
        ),
        sa.CheckConstraint(
            "available_balance NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_balances_finite_available",
        ),
        schema="banking",
    )
    op.create_table(
        "account_balance_openings",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("policy", sa.String(20), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_id", name="pk_account_balance_openings"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["banking.account_balances.account_id"],
            name="fk_account_balance_openings_balance",
        ),
        sa.CheckConstraint(
            "policy IN ('ORDINARY', 'HISTORICAL')", name="ck_account_balance_openings_policy"
        ),
        sa.CheckConstraint(
            "opening_balance NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_account_balance_openings_finite",
        ),
        sa.CheckConstraint(
            "policy = 'HISTORICAL' OR opening_balance >= 0",
            name="ck_account_balance_openings_negative_policy",
        ),
        schema="banking",
    )
    # Do not guess opening balances for existing accounts or replay their history.
    # Use the internal initialization service with an explicit authoritative value.


def downgrade() -> None:
    op.drop_table("account_balance_openings", schema="banking")
    op.drop_table("account_balances", schema="banking")
