"""Auth: signup / login / refresh (rotating) / me.

Contract (spec 03, binding):
  POST /auth/signup  {email, password, org_name} -> tokens + user + org + project
  POST /auth/login   {email, password}           -> tokens + user + org
  POST /auth/refresh {refresh_token}             -> new token pair (rotation)
  GET  /auth/me                                 -> current user + org + projects
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.schemas import auth as schemas
from app.services import billing

router = APIRouter(prefix="/auth", tags=["auth"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime) -> datetime:
    """SQLite returns datetimes offset-naive; interpret naive as UTC so
    comparisons with aware datetimes work on both backends."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "org"
    return slug[:60]


def _issue_pair(db: Session, user: m.User) -> schemas.TokenPair:
    """Create an access token + a fresh persisted refresh token."""
    access = create_access_token(user_id=user.id, org_id=user.org_id)
    refresh = new_refresh_token()
    db.add(m.RefreshToken(
        org_id=user.org_id,
        user_id=user.id,
        token_hash=hash_refresh_token(refresh),
        expires_at=refresh_token_expiry(),
    ))
    db.flush()
    return schemas.TokenPair(access_token=access, refresh_token=refresh)


def _unique_org_slug(db: Session, base: str) -> str:
    slug, i = base, 1
    while db.query(m.Organization).filter_by(slug=slug).first() is not None:
        i += 1
        slug = f"{base}-{i}"
    return slug


@router.post("/signup", response_model=schemas.AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: schemas.SignupRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    with deps.pre_auth_lookup(db):
        if db.query(m.User).filter_by(email=email).first() is not None:
            raise HTTPException(status_code=409, detail="email already registered")
        slug = _unique_org_slug(db, _slugify(payload.org_name))

    org = m.Organization(name=payload.org_name.strip(), slug=slug, plan="free")
    db.add(org)
    db.flush()  # org.id needed for RLS scoping below
    deps.set_rls_org(db, org.id)
    # Phase 8: every signup starts a 14-day cardless trial (full features).
    billing.start_trial(org)

    user = m.User(organization=org, email=email, password_hash=hash_password(payload.password), role="owner")
    db.add(user)
    project = m.Project(organization=org, name="Default project")
    db.add(project)
    db.flush()
    pair = _issue_pair(db, user)
    db.add(m.AuditLog(org_id=org.id, user_id=user.id, action="org.signup",
                      target_type="organization", target_id=str(org.id),
                      ip=request.client.host if request.client else None))
    db.commit()
    return schemas.AuthResponse(
        **pair.model_dump(),
        user=schemas.UserOut.model_validate(user),
        org=schemas.OrgOut.model_validate(org),
        project=schemas.ProjectOut.model_validate(project),
    )


@router.post("/login", response_model=schemas.AuthResponse)
def login(payload: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    with deps.pre_auth_lookup(db):
        user = db.query(m.User).filter_by(email=email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    deps.set_rls_org(db, user.org_id)
    # Re-load under the org-scoped policy (defense in depth, not just the bootstrap).
    user = db.get(m.User, user.id)
    org = db.get(m.Organization, user.org_id)
    project = (db.query(m.Project).filter_by(org_id=org.id)
               .order_by(m.Project.created_at).first())
    pair = _issue_pair(db, user)
    db.add(m.AuditLog(org_id=org.id, user_id=user.id, action="auth.login",
                      target_type="user", target_id=str(user.id),
                      ip=request.client.host if request.client else None))
    db.commit()
    return schemas.AuthResponse(
        **pair.model_dump(),
        user=schemas.UserOut.model_validate(user),
        org=schemas.OrgOut.model_validate(org),
        project=schemas.ProjectOut.model_validate(project) if project else None,
    )


@router.post("/refresh", response_model=schemas.TokenPair)
def refresh(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    digest = hash_refresh_token(payload.refresh_token)
    with deps.pre_auth_lookup(db):
        stored = db.query(m.RefreshToken).filter_by(token_hash=digest).first()
    if stored is None or stored.revoked_at is not None or _as_aware(stored.expires_at) <= _utcnow():
        raise HTTPException(status_code=401, detail="invalid or expired refresh token")
    deps.set_rls_org(db, stored.org_id)
    stored = db.get(m.RefreshToken, stored.id)  # re-load under org policy
    user = db.get(m.User, stored.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    # Rotation: revoke the presented token, issue a fresh pair.
    stored.revoked_at = _utcnow()
    pair = _issue_pair(db, user)
    db.commit()
    return pair


@router.get("/me", response_model=schemas.MeResponse)
def me(user: m.User = Depends(deps.get_current_user), db: Session = Depends(get_db)):
    org = db.get(m.Organization, user.org_id)
    projects = (db.query(m.Project).filter_by(org_id=org.id)
                .order_by(m.Project.created_at).all())
    return schemas.MeResponse(
        user=schemas.UserOut.model_validate(user),
        org=schemas.OrgOut.model_validate(org),
        projects=[schemas.ProjectOut.model_validate(p) for p in projects],
    )
