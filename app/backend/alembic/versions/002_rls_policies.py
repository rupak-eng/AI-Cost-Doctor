"""Row-Level Security: org isolation as defense in depth.

Every tenant table gets:
  ENABLE ROW LEVEL SECURITY + FORCE ROW LEVEL SECURITY
  (FORCE so the policy binds even the table owner — the app connects with a
  single role, and RLS must still hold)

and a policy:

  USING / WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)

`organizations` is keyed on `id`. `users`, `refresh_tokens`, and
`organizations` additionally allow a transaction-local `app.auth_lookup='1'`
bootstrap used ONLY by the pre-authentication lookups (login email
resolution, signup email/slug checks, refresh-token hash resolution); the
app sets the real org context immediately afterwards and clears the flag.

The application ALSO scopes every query by org_id — RLS is the second layer,
not the first.
"""
from __future__ import annotations

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# (table, org column, allow pre-auth bootstrap exception)
TABLES: list[tuple[str, str, bool]] = [
    ("organizations", "id", True),
    ("users", "org_id", True),
    ("refresh_tokens", "org_id", True),
    ("projects", "org_id", False),
    ("tenants", "org_id", False),
    ("provider_credentials", "org_id", False),
    ("api_keys", "org_id", False),
    ("usage_events", "org_id", False),
    ("cost_anomalies", "org_id", False),
    ("recommendations", "org_id", False),
    ("alerts", "org_id", False),
    ("alert_events", "org_id", False),
    ("audit_log", "org_id", False),
    # model_prices is a global catalog (no org_id) — intentionally no RLS.
]


def _predicate(org_col: str, bootstrap: bool) -> str:
    base = f"{org_col} = nullif(current_setting('app.org_id', true), '')::uuid"
    if bootstrap:
        base += " OR current_setting('app.auth_lookup', true) = '1'"
    return base


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # RLS is a Postgres feature; SQLite test runs skip it.
        return
    for table, org_col, bootstrap in TABLES:
        pred = _predicate(org_col, bootstrap)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} FOR ALL TO PUBLIC "
            f"USING ({pred}) WITH CHECK ({pred})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, _, _ in TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
