"""Local account-opening receipts; legacy identity tables are retained."""

import sqlalchemy as sa
from alembic import op

revision = "0007_customer_account_openings"
down_revision = "0006_create_customer_onboardings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_account_openings",
        sa.Column("customer_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("banking.accounts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        schema="banking",
    )
    # Preserve the account already opened by the previous onboarding workflow.
    op.execute("""
        INSERT INTO banking.customer_account_openings (customer_id, account_id, currency)
        SELECT o.customer_id, o.account_id, a.currency
        FROM banking.customer_onboardings o
        JOIN banking.accounts a ON a.id = o.account_id AND a.customer_id = o.customer_id
        WHERE o.account_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_table("customer_account_openings", schema="banking")
