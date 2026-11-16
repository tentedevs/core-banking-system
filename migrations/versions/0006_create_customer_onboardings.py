"""Durable onboarding identity for safe cross-service retries."""

import sqlalchemy as sa
from alembic import op

revision = "0006_create_customer_onboardings"
down_revision = "0005_create_actor_customer_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_onboardings",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("actor_id", name="pk_customer_onboardings"),
        sa.UniqueConstraint("customer_id", name="uq_customer_onboardings_customer_id"),
        sa.UniqueConstraint("account_id", name="uq_customer_onboardings_account_id"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["banking.accounts.id"], name="fk_customer_onboardings_account"
        ),
        sa.CheckConstraint(
            "fingerprint COLLATE \"C\" ~ '^[0-9a-f]{64}$'",
            name="ck_customer_onboardings_fingerprint",
        ),
        schema="banking",
    )


def downgrade() -> None:
    op.drop_table("customer_onboardings", schema="banking")
