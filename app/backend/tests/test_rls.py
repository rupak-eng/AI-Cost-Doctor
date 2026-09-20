"""RLS isolation tests — Postgres only.

Verifies the defense-in-depth layer: with FORCE ROW LEVEL SECURITY enabled,
a session confined via `SET LOCAL app.org_id` cannot see another org's rows,
and a session with no context sees nothing at all.
"""
import uuid

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
