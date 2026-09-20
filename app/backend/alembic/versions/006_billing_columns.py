"""Phase 8: billing columns on organizations + stripe_webhook_events table.

checkfirst: migration 001 creates all metadata tables via create_all, so on
fresh databases these columns/tables already exist; on databases upgrading
from 005 they need to be added.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

NEW_COLUMNS = [
    ("trial_ends_at", sa.DateTime(timezone=True)),
    ("stripe_customer_id", sa.Text()),
    ("stripe_subscription_id", sa.Text()),
    ("stripe_pending_session_id", sa.Text()),
    ("subscription_status", sa.Text()),
]


def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("organizations")}
    for name, coltype in NEW_COLUMNS:
        if name not in existing:
            op.add_column("organizations", sa.Column(name, coltype, nullable=True))

    if not bind.dialect.has_table(bind, "stripe_webhook_events"):
        uuid_type = PG_UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.Uuid()
        op.create_table(
            "stripe_webhook_events",
            sa.Column("id", uuid_type, primary_key=True,
                      server_default=sa.text("gen_random_uuid()") if bind.dialect.name == "postgresql" else None),
            sa.Column("event_id", sa.Text(), nullable=False, unique=True),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("org_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )
        # NOTE: intentionally no RLS on this table (like model_prices) —
        # event IDs are not sensitive. See the model docstring.


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "stripe_webhook_events"):
        op.drop_table("stripe_webhook_events")
    existing = {c["name"] for c in sa.inspect(bind).get_columns("organizations")}
    for name, _ in NEW_COLUMNS:
        if name in existing:
            op.drop_column("organizations", name)
