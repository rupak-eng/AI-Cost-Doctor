"""Shared FastAPI dependencies: DB session, JWT auth, RLS tenant context.

Row-Level Security bootstrap:
- Authenticated requests: the JWT carries org_id; we SET LOCAL app.org_id
  before any org-scoped query, so the FORCE-enabled RLS policies (migration
  002) confine every statement to the caller's org.
- Pre-auth lookups (login/signup/refresh): the user row is not yet known, so
  these run under a narrow `app.auth_lookup` bootstrap flag that the `users`
  (and `refresh_tokens`) RLS policies explicitly allow for email/hash
  resolution only. The flag is transaction-local and cleared on commit; the
  real org context is set immediately after the org is resolved/created.
- Demo endpoints: public, but the demo org has a deterministic UUID, so we
  set app.org_id to it directly — RLS still applies, no bypass.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as m
from app.core.db import get_db
from app.core.security import decode_token
from app.services.seed_demo import demo_org_id

bearer_scheme = HTTPBearer(auto_error=True)


def _is_postgres(db: Session) -> bool:
    return db.bind.dialect.name == "postgresql" if db.bind else False


def set_rls_org(db: Session, org_id: uuid.UUID | str) -> None:
    """Confine this transaction to one org (defense in depth under RLS).

    Also clears the pre-auth bootstrap flag so that from here on every
    statement is strictly org-scoped. No-op on non-Postgres (tests).
    """
    if not _is_postgres(db):
        return
    db.execute(text("SET LOCAL app.org_id = :org_id"), {"org_id": str(org_id)})
    db.execute(text("SET LOCAL app.auth_lookup = ''"))


@contextmanager
def pre_auth_lookup(db: Session):
    """Narrow RLS bootstrap for resolving a user by email / refresh-token
    hash before authentication. See module docstring. No-op on non-Postgres.
    """
    if _is_postgres(db):
        db.execute(text("SET LOCAL app.auth_lookup = '1'"))
    try:
        yield
    finally:
        pass  # SET LOCAL dies with the transaction


def _unauthorized(detail: str = "not authenticated") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> m.User:
    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except pyjwt.ExpiredSignatureError:
        raise _unauthorized("token expired")
    except pyjwt.PyJWTError:
        raise _unauthorized("invalid token")
    set_rls_org(db, payload["org_id"])
    user = db.get(m.User, uuid.UUID(payload["sub"]))
    if user is None:
        raise _unauthorized("user not found")
    return user


def get_demo_org(db: Session = Depends(get_db)) -> m.Organization:
    """Resolve the synthetic DemoCo org and pin RLS to it (public endpoint)."""
    org_id = demo_org_id()
    set_rls_org(db, org_id)
    org = db.get(m.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="demo dataset not seeded — POST /demo/seed first")
    return org


def get_demo_project(db: Session, org: m.Organization) -> m.Project:
    project = db.query(m.Project).filter_by(org_id=org.id).order_by(m.Project.created_at).first()
    if project is None:
        raise HTTPException(status_code=404, detail="demo project missing")
    return project
