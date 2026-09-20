"""Customer project endpoints (JWT auth).

  POST   /projects/{project_id}/api-keys            create an ingest key
                                                    (plaintext shown ONCE)
  GET    /projects/{project_id}/api-keys            list keys (no secrets)
  DELETE /projects/{project_id}/api-keys/{key_id}   revoke a key
  GET    /projects/{project_id}/pnl?days=30         per-tenant P&L
  POST   /projects/{project_id}/investigate         root-cause facts
  GET    /projects/{project_id}/dashboard?days=30  spend overview
                                                    (7, 30, or 90 days)
  GET    /projects/{project_id}/anomalies?days=30   deterministic anomaly
                                                    feed (refresh-on-read),
                                                    severity-ordered +
                                                    unread_count
  POST   /projects/{project_id}/anomalies/{id}/acknowledge
                                                    mark an anomaly
                                                    acknowledged

All responses carry "data_label": "customer". Every lookup is org-scoped
(explicit org check + RLS); cross-org access → 404.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import api_keys as key_schemas
from app.schemas import projects as schemas
from app.services import anomalies as anomalies_service
from app.services import billing
from app.services.dashboard import compute_dashboard
from app.services.investigate import TenantNotFoundError, explain_investigation, investigate_tenant
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


@router.post("", response_model=schemas.ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: schemas.ProjectCreateRequest,
                   user: m.User = Depends(deps.get_current_user),
                   db: Session = Depends(get_db)):
    """Create an additional project. Gated by the plan's project cap
    (free/starter: 1, growth: 5) — 402 when the org is at its limit."""
    billing.check_project_limit(user, db)
    project = m.Project(org_id=user.org_id, name=payload.name.strip())
    db.add(project)
    db.flush()
    db.commit()
    return schemas.ProjectOut(id=project.id, name=project.name,
                              created_at=project.created_at)


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


@router.get("/{project_id}/investigate", response_model=schemas.ProjectInvestigateResponse)
def project_investigate_get(project_id: str, tenant: str = Query(min_length=1),
                            days: int = Query(default=30, ge=1, le=365),
                            user: m.User = Depends(deps.get_current_user),
                            db: Session = Depends(get_db)):
    """GET variant of investigate — same deterministic engine as POST."""
    project = deps.get_org_project(db, user, project_id)
    try:
        result = investigate_tenant(db, user.org_id, project.id, tenant, days=days)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail="tenant not found")
    return schemas.ProjectInvestigateResponse(**result)


class InvestigateExplainRequest(BaseModel):
    tenant_external_id: str = Field(min_length=1)
    days: int = Field(default=30, ge=1, le=365)


class InvestigateExplainResponse(BaseModel):
    data_label: str = "customer"
    tenant_external_id: str
    narrative: str
    # "template" (deterministic, always available) or "llm" (optional rewording
    # of the template — the LLM never invents numbers).
    narrative_source: str = Field(pattern="^(template|llm)$")


@router.post("/{project_id}/investigate/explain", response_model=InvestigateExplainResponse)
def project_investigate_explain(project_id: str, payload: InvestigateExplainRequest,
                                user: m.User = Depends(deps.get_current_user),
                                db: Session = Depends(get_db)):
    """Narrative explanation of the deterministic investigation facts.

    Template prose by default; if NARRATIVE_LLM_API_KEY is configured the
    template may be reworded by the LLM (facts in, prose out — the LLM never
    computes or invents numbers). Any polish failure falls back to template.
    """
    project = deps.get_org_project(db, user, project_id)
    try:
        result = explain_investigation(db, user.org_id, project.id,
                                       payload.tenant_external_id, days=payload.days)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail="tenant not found")
    return InvestigateExplainResponse(
        tenant_external_id=payload.tenant_external_id, **result)


@router.get("/{project_id}/dashboard", response_model=schemas.ProjectDashboardResponse)
def project_dashboard(project_id: str,
                      days: int = Query(default=30),
                      user: m.User = Depends(deps.get_current_user),
                      db: Session = Depends(get_db)):
    """Spend overview for a project: totals, daily trend, breakdowns by model
    and application, and top cost-driving tenants.

    Every figure aggregates usage_events.cost_calculated_usd — the
    deterministic engine's output. No pricing math happens here.
    """
    if days not in (7, 30, 90):
        raise HTTPException(
            status_code=400, detail="days must be one of 7, 30, 90")
    project = deps.get_org_project(db, user, project_id)
    data = compute_dashboard(db, user.org_id, project.id, days=days)
    return schemas.ProjectDashboardResponse(**data)


@router.get("/{project_id}/anomalies", response_model=schemas.ProjectAnomaliesResponse)
def project_anomalies(project_id: str,
                      days: int = Query(default=30, ge=1, le=90),
                      user: m.User = Depends(deps.get_current_user),
                      db: Session = Depends(get_db)):
    """Anomaly feed for a project, severity-ordered with an unread badge count.

    Refresh-on-read: the deterministic detectors run on every call and upsert
    idempotently (fingerprint dedupe), so the feed is always current without
    a background scheduler. The detection write is committed here — without
    a commit the request-scoped session would roll back and dedupe could
    never work across requests. Every figure derives from
    usage_events.cost_calculated_usd — reported/estimated costs are never
    inputs.
    """
    if days not in (7, 30, 90):
        raise HTTPException(
            status_code=400, detail="days must be one of 7, 30, 90")
    # Paid feature: the anomaly feed requires an active trial or paid plan.
    billing.require_paid_feature(user, db, "anomaly_reads")
    project = deps.get_org_project(db, user, project_id)
    result = anomalies_service.list_anomalies(db, user.org_id, project.id, days=days)
    db.commit()
    return schemas.ProjectAnomaliesResponse(**result)


@router.post("/{project_id}/anomalies/{anomaly_id}/acknowledge",
             response_model=schemas.AnomalyOut)
def acknowledge_project_anomaly(project_id: str, anomaly_id: str,
                                user: m.User = Depends(deps.get_current_user),
                                db: Session = Depends(get_db)):
    """Mark an anomaly acknowledged. Cross-org ids → 404 (no existence leak)."""
    project = deps.get_org_project(db, user, project_id)
    try:
        aid = uuid.UUID(str(anomaly_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="anomaly not found")
    row = anomalies_service.acknowledge_anomaly(db, user.org_id, project.id, aid)
    if row is None:
        raise HTTPException(status_code=404, detail="anomaly not found")
    db.commit()
    tenant_names = {t.external_id: t.name for t in
                    db.query(m.Tenant).filter_by(org_id=user.org_id,
                                                 project_id=project.id).all()}
    return schemas.AnomalyOut(**anomalies_service.anomaly_to_dict(row, tenant_names))
