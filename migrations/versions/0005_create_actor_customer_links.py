"""Associate auth actors with externally managed CRP customers."""

import sqlalchemy as sa
from alembic import op

revision = "0005_create_actor_customer_links"
down_revision = "0004_create_transaction_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "actor_customer_links",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("actor_id", name="pk_actor_customer_links"),
        schema="banking",
    )
    op.create_index(
        "ix_actor_customer_links_customer_id",
        "actor_customer_links",
        ["customer_id"],
        schema="banking",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_actor_customer_links_customer_id", table_name="actor_customer_links", schema="banking"
    )
    op.drop_table("actor_customer_links", schema="banking")
