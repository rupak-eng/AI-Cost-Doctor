"""Customer project endpoints (JWT auth).

  POST   /projects/{project_id}/api-keys            create an ingest key
                                                    (plaintext shown ONCE)
  GET    /projects/{project_id}/api-keys            list keys (no secrets)
  DELETE /projects/{project_id}/api-keys/{key_id}   revoke a key
  GET    /projects/{project_id}/pnl?days=30         per-tenant P&L
  POST   /projects/{project_id}/investigate         root-cause facts

All responses carry "data_label": "customer". Every lookup is org-scoped
(explicit org check + RLS); cross-org access → 404.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import api_keys as key_schemas
from app.schemas import projects as schemas
from app.services.investigate import TenantNotFoundError, investigate_tenant
from app.services.pnl import compute_pnl

router = APIRouter(prefix="/projects", tags=["projects"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_api_key() -> tuple[str, str, str]:
    """Return (plaintext, sha256_hex_digest, prefix).

    The secret is exactly 48 chars of randomness (secrets.token_urlsafe(36)).
    Only the digest is persisted; the plaintext is shown once at creation.
    """
    raw = secrets.token_urlsafe(36)
    assert len(raw) == 48, f"unexpected key length {len(raw)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest, raw[:8]


@router.post("/{project_id}/api-keys", response_model=key_schemas.ApiKeyCreated,
             status_code=status.HTTP_201_CREATED)
def create_api_key(project_id: str, payload: key_schemas.ApiKeyCreateRequest,
                   user: m.User = Depends(deps.get_current_user),
                   db: Session = Depends(get_db)):
    project = deps.get_org_project(db, user, project_id)
    for _ in range(3):  # hash collisions are ~impossible; retry anyway
        raw, digest, prefix = _new_api_key()
        key = m.ApiKey(org_id=user.org_id, project_id=project.id,
                       name=payload.name.strip(), key_hash=digest, key_prefix=prefix)
        db.add(key)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            deps.set_rls_org(db, user.org_id)
            continue
        break
    else:  # pragma: no cover - unreachable in practice
        raise HTTPException(status_code=500, detail="could not generate a unique API key")
    db.commit()
    return key_schemas.ApiKeyCreated(
        id=key.id, name=key.name, key_prefix=key.key_prefix,
        api_key=raw, created_at=key.created_at)


@router.get("/{project_id}/api-keys", response_model=list[key_schemas.ApiKeyOut])
def list_api_keys(project_id: str, user: m.User = Depends(deps.get_current_user),
                  db: Session = Depends(get_db)):
    project = deps.get_org_project(db, user, project_id)
    keys = (db.query(m.ApiKey)
            .filter_by(org_id=user.org_id, project_id=project.id)
            .order_by(m.ApiKey.created_at).all())
    return keys


@router.delete("/{project_id}/api-keys/{key_id}", response_model=key_schemas.ApiKeyOut)
def revoke_api_key(project_id: str, key_id: str,
                   user: m.User = Depends(deps.get_current_user),
                   db: Session = Depends(get_db)):
    project = deps.get_org_project(db, user, project_id)
    try:
        kid = uuid.UUID(str(key_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="API key not found")
    key = db.get(m.ApiKey, kid)
    if key is None or key.project_id != project.id or key.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked_at = _utcnow()
    db.commit()
    return key


@router.get("/{project_id}/pnl", response_model=schemas.ProjectPnLResponse)
def project_pnl(project_id: str, days: int = Query(default=30, ge=1, le=365),
                user: m.User = Depends(deps.get_current_user),
                db: Session = Depends(get_db)):
    project = deps.get_org_project(db, user, project_id)
    rows = compute_pnl(db, user.org_id, project.id, days=days)
    return schemas.ProjectPnLResponse(
        tenants=[schemas.ProjectPnLRow(**r) for r in rows])


@router.post("/{project_id}/investigate", response_model=schemas.ProjectInvestigateResponse)
def project_investigate(project_id: str, payload: schemas.ProjectInvestigateRequest,
                        days: int = Query(default=30, ge=1, le=365),
                        user: m.User = Depends(deps.get_current_user),
                        db: Session = Depends(get_db)):
    project = deps.get_org_project(db, user, project_id)
    try:
        result = investigate_tenant(db, user.org_id, project.id,
                                    payload.tenant_external_id, days=days)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail="tenant not found")
    return schemas.ProjectInvestigateResponse(**result)
