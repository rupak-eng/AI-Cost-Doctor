"""Phase 3 schema changes.

1. tenants.monthly_revenue_usd becomes NULLABLE. NULL means "revenue not
   yet known" (tenant auto-created from an event/CSV before revenue was
   provided) — distinct from a measured 0. The P&L engine reports margin
   None / status 'unknown' for both, but the schema no longer forces callers
   to write a fake 0.
2. api_keys RLS policy gains the pre-auth bootstrap exception (same pattern
   as users/refresh_tokens in 002) so the event-ingest path can resolve an
   opaque project API key by its SHA-256 hash before any org context exists.
   The bootstrap applies to USING (reads) only — inserts/updates still
   require the real org context. The window is transaction-local, used for a
   single key_hash lookup, and cleared by set_rls_org immediately after.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

_API_KEYS_READ_PRED = (
    "org_id = nullif(current_setting('app.org_id', true), '')::uuid "
    "OR current_setting('app.auth_lookup', true) = '1'"
)
_API_KEYS_WRITE_PRED = (
    "org_id = nullif(current_setting('app.org_id', true), '')::uuid"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # RLS is a Postgres feature; SQLite test runs skip migrations.
        return
    op.alter_column(
        "tenants",
        "monthly_revenue_usd",
        existing_type=sa.Numeric(12, 2),
        nullable=True,
    )
    op.execute("DROP POLICY IF EXISTS org_isolation ON api_keys")
    op.execute(
        "CREATE POLICY org_isolation ON api_keys FOR ALL TO PUBLIC "
        f"USING ({_API_KEYS_READ_PRED}) WITH CHECK ({_API_KEYS_WRITE_PRED})"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS org_isolation ON api_keys")
    op.execute(
        "CREATE POLICY org_isolation ON api_keys FOR ALL TO PUBLIC "
        f"USING ({_API_KEYS_WRITE_PRED}) WITH CHECK ({_API_KEYS_WRITE_PRED})"
    )
    op.execute("UPDATE tenants SET monthly_revenue_usd = 0 WHERE monthly_revenue_usd IS NULL")
    op.alter_column(
        "tenants",
        "monthly_revenue_usd",
        existing_type=sa.Numeric(12, 2),
        nullable=False,
    )
