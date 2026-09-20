"""Phase 4: provider-reported cost buckets (kept separate from usage events).

See specs/04-provider-integration-notes.md §3: neither OpenAI's
/organization/costs nor Anthropic's /cost_report breaks reported dollars down
by model, so reported cost is stored here as org-level reconciliation
evidence — never allocated to models.
"""
from __future__ import annotations

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app import models as m  # noqa: F401

    # checkfirst: migration 001 creates all metadata tables via create_all,
    # so on fresh databases this table already exists; on databases
    # upgrading from 003 it needs to be created.
    m.ProviderCostReport.__table__.create(op.get_bind(), checkfirst=True)

    if op.get_bind().dialect.name != "postgresql":
        return  # RLS is a Postgres feature; SQLite test runs skip it.
    pred = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"
    op.execute("ALTER TABLE provider_cost_reports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE provider_cost_reports FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS org_isolation ON provider_cost_reports")
    op.execute(
        "CREATE POLICY org_isolation ON provider_cost_reports FOR ALL TO PUBLIC "
        f"USING ({pred}) WITH CHECK ({pred})"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS org_isolation ON provider_cost_reports")
    from app import models as m  # noqa: F401

    m.ProviderCostReport.__table__.drop(op.get_bind())
