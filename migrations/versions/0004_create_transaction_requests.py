"""Persist request fingerprints for atomic monetary idempotency.

Revision ID: 0004_create_transaction_requests
Revises: 0003_create_account_balances
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_create_transaction_requests"
down_revision = "0003_create_account_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transaction_requests",
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key", name="pk_transaction_requests"),
        sa.UniqueConstraint("transaction_id", name="uq_transaction_requests_transaction_id"),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["banking.transactions.id"],
            name="fk_transaction_requests_transaction_id",
        ),
        sa.CheckConstraint("idempotency_key ~ '[^[:space:]]'", name="ck_transaction_requests_key"),
        sa.CheckConstraint(
            "fingerprint COLLATE \"C\" ~ '^[0-9a-f]{64}$'",
            name="ck_transaction_requests_fingerprint",
        ),
        schema="banking",
    )


def downgrade() -> None:
    op.drop_table("transaction_requests", schema="banking")
