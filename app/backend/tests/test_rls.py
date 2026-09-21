"""RLS isolation tests — Postgres only.

Verifies the defense-in-depth layer: with FORCE ROW LEVEL SECURITY enabled,
a session confined via `SET LOCAL app.org_id` cannot see another org's rows,
and a session with no context sees nothing at all.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app import models as m
from app.core.security import hash_password
from tests.conftest import requires_pg


def _mk_org(db, name):
    """Create org + user + project while satisfying the RLS WITH CHECK.

    The org row is inserted under the narrow pre-auth bootstrap exception;
    children are inserted after pinning the real org context.
    """
    org = m.Organization(name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}")
    db.execute(text("SET LOCAL app.auth_lookup = '1'"))
    db.add(org)
    db.flush()
    db.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(org.id)})
    db.execute(text("SET LOCAL app.auth_lookup = ''"))
    user = m.User(organization=org, email=f"{uuid.uuid4().hex}@example.com",
                  password_hash=hash_password("password-123"), role="owner")
    db.add(user)
    proj = m.Project(organization=org, name="P")
    db.add(proj)
    db.flush()
    # Leave the session without a pinned context for the test body.
    db.execute(text("SET LOCAL app.org_id = ''"))
    return org, user, proj


@requires_pg
class TestRlsIsolation:
    def test_no_context_sees_nothing(self, db):
        org, _, _ = _mk_org(db, "rls-a")
        db.execute(text("SET LOCAL app.org_id = ''"))
        assert db.query(m.User).count() == 0
        assert db.query(m.Organization).count() == 0
        assert db.query(m.Project).count() == 0

    def test_org_context_confines_reads(self, db):
        org_a, user_a, _ = _mk_org(db, "rls-a")
        org_b, user_b, _ = _mk_org(db, "rls-b")

        db.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(org_a.id)})
        users = db.query(m.User).all()
        assert [u.id for u in users] == [user_a.id]
        # Evict the identity-map cache so db.get() really hits Postgres:
        # RLS must filter the other org's row.
        db.expunge_all()
        assert db.get(m.User, user_b.id) is None
        assert db.get(m.Organization, org_b.id) is None
        assert db.get(m.Organization, org_a.id) is not None

    def test_context_switch(self, db):
        org_a, user_a, _ = _mk_org(db, "rls-a")
        org_b, user_b, _ = _mk_org(db, "rls-b")

        db.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(org_a.id)})
        assert [u.id for u in db.query(m.User).all()] == [user_a.id]
        # A later SET LOCAL in the same transaction overrides the context.
        db.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(org_b.id)})
        assert [u.id for u in db.query(m.User).all()] == [user_b.id]

    def test_insert_outside_context_blocked(self, db):
        # WITH CHECK: inserting a row for another org while confined fails.
        org_a, _, _ = _mk_org(db, "rls-a")
        org_b, _, _ = _mk_org(db, "rls-b")
        db.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(org_a.id)})
        db.add(m.Project(org_id=org_b.id, name="sneaky"))
        with pytest.raises(Exception):
            db.flush()


def _pin(db, org_id):
    db.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(org_id)})


def _unpin(db):
    db.execute(text("SET LOCAL app.org_id = ''"))


@requires_pg
class TestRlsTenantTables:
    """Per-table RLS: org A can neither read nor modify org B's rows.

    Covers the tenant-scoped domains: projects, tenants, usage events
    (P&L inputs), cost anomalies, recommendations, provider credentials,
    API keys, and the billing columns on the organization row.
    """

    def _seed_pair(self, db):
        data = {}
        for name in ("rls-xa", "rls-xb"):
            org, _, proj = _mk_org(db, name)
            _pin(db, org.id)
            tenant = m.Tenant(
                org_id=org.id, project_id=proj.id,
                external_id=f"ext-{name}", name=f"{name} tenant",
                monthly_revenue_usd=Decimal("100"))
            db.add(tenant)
            db.flush()
            ev = m.UsageEvent(
                org_id=org.id, project_id=proj.id, source="event_api",
                provider="openai", model="gpt-4o-mini",
                tenant_id=tenant.external_id,
                occurred_at=datetime.now(timezone.utc),
                input_tokens=100, output_tokens=50,
                cost_calculated_usd=Decimal("0.01"))
            db.add(ev)
            db.flush()
            anomaly = m.CostAnomaly(
                org_id=org.id, project_id=proj.id, dimension="tenant",
                dimension_value=tenant.external_id, metric="cost_usd",
                severity="warning", status="open", evidence={})
            db.add(anomaly)
            db.flush()
            rec = m.Recommendation(
                org_id=org.id, project_id=proj.id, type="model_routing",
                title="t", est_savings_usd_mo=Decimal("5"),
                confidence="high")
            db.add(rec)
            db.flush()
            cred = m.ProviderCredential(
                org_id=org.id, provider="openai",
                encrypted_key=b"enc", key_last4="1234", status="active")
            db.add(cred)
            db.flush()
            key = m.ApiKey(
                org_id=org.id, project_id=proj.id, name="k",
                key_hash=f"hash-{name}", key_prefix="prefix")
            db.add(key)
            db.flush()
            _unpin(db)
            # Give org B billing-shaped data so the leak test is meaningful.
            if name == "rls-xb":
                _pin(db, org.id)
                org.plan = "growth"
                org.stripe_customer_id = "cus_secret_b"
                org.subscription_status = "active"
                db.flush()
                _unpin(db)
            data[name] = {"org": org, "proj": proj, "tenant": tenant,
                          "ev": ev, "anomaly": anomaly, "rec": rec,
                          "cred": cred, "key": key}
        return data["rls-xa"], data["rls-xb"]

    def test_cross_org_reads_blocked(self, db):
        a, b = self._seed_pair(db)
        db.expunge_all()
        _pin(db, a["org"].id)

        # Every tenant table: only A's rows visible; B's rows unreachable.
        assert [p.id for p in db.query(m.Project).all()] == [a["proj"].id]
        assert [t.id for t in db.query(m.Tenant).all()] == [a["tenant"].id]
        assert [e.id for e in db.query(m.UsageEvent).all()] == [a["ev"].id]
        assert [x.id for x in db.query(m.CostAnomaly).all()] == [a["anomaly"].id]
        assert [r.id for r in db.query(m.Recommendation).all()] == [a["rec"].id]
        assert [c.id for c in db.query(m.ProviderCredential).all()] == [a["cred"].id]
        assert [k.id for k in db.query(m.ApiKey).all()] == [a["key"].id]

        db.expunge_all()  # bypass the identity-map cache: RLS must filter
        assert db.get(m.Project, b["proj"].id) is None
        assert db.get(m.Tenant, b["tenant"].id) is None
        assert db.get(m.UsageEvent, b["ev"].id) is None
        assert db.get(m.CostAnomaly, b["anomaly"].id) is None
        assert db.get(m.Recommendation, b["rec"].id) is None
        assert db.get(m.ProviderCredential, b["cred"].id) is None
        assert db.get(m.ApiKey, b["key"].id) is None

    def test_billing_columns_do_not_leak(self, db):
        # The organization row carries plan + Stripe customer/subscription
        # ids; org A must not resolve org B's row at all.
        a, b = self._seed_pair(db)
        db.expunge_all()
        _pin(db, a["org"].id)
        assert db.get(m.Organization, b["org"].id) is None
        assert db.get(m.Organization, a["org"].id) is not None

    def test_cross_org_update_blocked(self, db):
        a, b = self._seed_pair(db)
        _pin(db, a["org"].id)
        # RLS USING clause: the UPDATE matches zero rows for org B's project.
        n = (db.query(m.Project).filter_by(id=b["proj"].id)
             .update({"name": "hacked"}, synchronize_session=False))
        assert n == 0
        db.flush()
        # And the row is untouched when viewed from org B.
        _pin(db, b["org"].id)
        db.expunge_all()
        assert db.get(m.Project, b["proj"].id).name == "P"

    def test_cross_org_delete_blocked(self, db):
        a, b = self._seed_pair(db)
        _pin(db, a["org"].id)
        n = (db.query(m.UsageEvent).filter_by(id=b["ev"].id)
             .delete(synchronize_session=False))
        assert n == 0
        db.flush()
        _pin(db, b["org"].id)
        db.expunge_all()
        assert db.get(m.UsageEvent, b["ev"].id) is not None

    def test_cross_org_insert_blocked(self, db):
        # WITH CHECK on every tenant table, not just projects.
        a, b = self._seed_pair(db)
        _pin(db, a["org"].id)
        db.add(m.Tenant(org_id=b["org"].id, project_id=b["proj"].id,
                        external_id="ext-evil", name="evil"))
        with pytest.raises(Exception):
            db.flush()
        # Fixture teardown rolls back the aborted transaction.
