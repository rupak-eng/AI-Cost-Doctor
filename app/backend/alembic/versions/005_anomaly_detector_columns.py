"""Phase 6: detector + fingerprint columns on cost_anomalies.

Refresh-on-read detection needs to know which detector produced a row and to
dedupe idempotently, so both travel as real columns (queryable) rather than
buried in the evidence JSON.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # checkfirst: migration 001 creates all metadata tables via create_all,
    # so on fresh databases these columns already exist; on databases
    # upgrading from 004 they need to be added.
    existing = {c["name"] for c in sa.inspect(bind).get_columns("cost_anomalies")}
    if "detector" not in existing:
        op.add_column("cost_anomalies", sa.Column("detector", sa.Text(), nullable=True))
    if "fingerprint" not in existing:
        op.add_column("cost_anomalies", sa.Column("fingerprint", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("cost_anomalies")}
    if "fingerprint" in existing:
        op.drop_column("cost_anomalies", "fingerprint")
    if "detector" in existing:
        op.drop_column("cost_anomalies", "detector")
