"""Provider connections (POST /integrations/providers, JWT auth).

- POST   /integrations/providers            connect: validate the Admin key
  against the real provider API, then store it encrypted (never plaintext).
- GET    /integrations/providers            list (key material never returned)
- DELETE /integrations/providers/{id}       disconnect
- POST   /integrations/providers/{id}/sync   pull usage + cost reports into
  usage_events / provider_cost_reports
- GET    /integrations/providers/{id}/sync-status

Key validation calls the provider live: a bad/expired key or a non-admin
key fails here with the provider's own error — we never store a key we
couldn't verify.
"""
from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import providers as schemas
from app.services import billing
from app.services.providers import anthropic as anthropic_mod
from app.services.providers import openai as openai_mod
from app.services.providers.base import ProviderError
from app.services.providers.sync import SyncSummary, sync_provider
from app.services.secrets import SecretsError, encrypt_secret, key_last4

router = APIRouter(prefix="/integrations/providers", tags=["providers"])


def _client_for(provider: str, api_key: str,
                transport: httpx.BaseTransport | None = None):
    if provider == "openai":
        return openai_mod.OpenAIClient(api_key, transport=transport)
    if provider == "anthropic":
        return anthropic_mod.AnthropicClient(api_key, transport=transport)
    raise HTTPException(status_code=400, detail=f"unsupported provider: {provider}")


def _to_info(cred: m.ProviderCredential) -> schemas.ProviderCredentialInfo:
    return schemas.ProviderCredentialInfo(
        id=str(cred.id), provider=cred.provider, label=cred.label,
        key_last4=cred.key_last4, status=cred.status,
        last_sync_at=cred.last_sync_at)


def _get_cred(db: Session, user: m.User, cred_id: str) -> m.ProviderCredential:
    try:
        cid = uuid.UUID(str(cred_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="provider credential not found")
    cred = db.get(m.ProviderCredential, cid)
    if cred is None or cred.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="provider credential not found")
    return cred


@router.post("", response_model=schemas.ProviderCredentialInfo,
             status_code=status.HTTP_201_CREATED)
def connect_provider(body: schemas.ProviderConnectRequest,
                     user: m.User = Depends(deps.get_current_user),
                     db: Session = Depends(get_db)):
    # 1. Validate against the real provider API before storing anything.
    client = _client_for(body.provider, body.api_key)
    try:
        client.validate()
    except ProviderError as exc:
        detail = exc.detail
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
        if exc.kind == "rate_limited":
            code = status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=detail)
    finally:
        client.close()

    # 2. Encrypt and store. Plaintext key never touches the database.
    try:
        encrypted = encrypt_secret(body.api_key, org_id=str(user.org_id))
    except SecretsError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    cred = m.ProviderCredential(
        org_id=user.org_id, provider=body.provider,
        label=(body.label or "").strip() or None,
        encrypted_key=encrypted, key_last4=key_last4(body.api_key),
        status="active")
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return _to_info(cred)


@router.get("", response_model=list[schemas.ProviderCredentialInfo])
def list_providers(user: m.User = Depends(deps.get_current_user),
                   db: Session = Depends(get_db)):
    creds = (db.query(m.ProviderCredential)
             .filter_by(org_id=user.org_id)
             .order_by(m.ProviderCredential.created_at.desc()).all())
    return [_to_info(c) for c in creds]


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_provider(cred_id: str,
                        user: m.User = Depends(deps.get_current_user),
                        db: Session = Depends(get_db)):
    cred = _get_cred(db, user, cred_id)
    db.delete(cred)
    db.commit()


@router.post("/{cred_id}/sync", response_model=schemas.ProviderSyncResponse)
def sync_now(cred_id: str, body: schemas.ProviderSyncRequest,
             project_id: str = Query(...),
             user: m.User = Depends(deps.get_current_user),
             db: Session = Depends(get_db)):
    # Paid feature: provider sync requires an active trial or paid plan.
    billing.require_paid_feature(user, db, "provider_sync")
    cred = _get_cred(db, user, cred_id)
    project = deps.get_org_project(db, user, project_id)
    try:
        summary: SyncSummary = sync_provider(
            db, org_id=user.org_id, project_id=project.id, credential=cred,
            days_back=body.days_back,
            extra_group_by=tuple(body.extra_group_by))
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=exc.detail)
    return schemas.ProviderSyncResponse(**summary.__dict__)


@router.get("/{cred_id}/sync-status", response_model=schemas.ProviderCredentialInfo)
def sync_status(cred_id: str,
                user: m.User = Depends(deps.get_current_user),
                db: Session = Depends(get_db)):
    return _to_info(_get_cred(db, user, cred_id))
