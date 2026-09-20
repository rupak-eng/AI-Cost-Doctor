"""Event ingest (POST /ingest/events).

Auth: X-API-Key header carrying a project ingest key (no JWT). The key is
resolved by deps.resolve_api_key — unknown/revoked keys → 401.

Each event's cost_calculated_usd is computed deterministically via
app.services.costing with the price effective at occurred_at. When the
catalog has no price for (provider, model), the event is still stored but
cost_calculated_usd stays NULL and the event counts as `unpriced` — we never
invent a price. Tenants referenced by tenant_id are auto-created
(name = external_id, revenue NULL) so the P&L can list them immediately.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import ingest as schemas
from app.services.costing import load_catalog_from_db, price_event

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _ensure_tenants(db: Session, key: m.ApiKey, tenant_ids: set[str]) -> None:
    """Auto-create tenant rows for new external_ids (name = external_id,
    revenue NULL = unknown)."""
    tenant_ids = {t for t in tenant_ids if t}
    if not tenant_ids:
        return
    existing = {
        r[0] for r in
        db.query(m.Tenant.external_id)
        .filter_by(org_id=key.org_id, project_id=key.project_id)
        .filter(m.Tenant.external_id.in_(tenant_ids)).all()
    }
    for ext in sorted(tenant_ids - existing):
        db.add(m.Tenant(org_id=key.org_id, project_id=key.project_id,
                        external_id=ext, name=ext, monthly_revenue_usd=None))
    db.flush()


@router.post("/events", response_model=schemas.IngestEventsResponse)
def ingest_events(payload: schemas.IngestEventsRequest,
                  key: m.ApiKey = Depends(deps.resolve_api_key),
                  db: Session = Depends(get_db)):
    catalog = load_catalog_from_db(db)
    _ensure_tenants(db, key, {e.tenant_id for e in payload.events if e.tenant_id})

    rows, unpriced, total = [], 0, Decimal(0)
    for ev in payload.events:
        calculated = price_event(
            catalog, provider=ev.provider, model=ev.model, at=ev.occurred_at,
            input_tokens=ev.input_tokens, output_tokens=ev.output_tokens,
            cached_input_tokens=ev.cached_input_tokens,
            reasoning_tokens=ev.reasoning_tokens)
        if calculated is None:
            unpriced += 1
        else:
            total += calculated
        rows.append(m.UsageEvent(
            org_id=key.org_id, project_id=key.project_id, source="event_api",
            provider=ev.provider, model=ev.model, application=ev.application,
            environment=ev.environment, tenant_id=ev.tenant_id,
            occurred_at=ev.occurred_at,
            input_tokens=ev.input_tokens, output_tokens=ev.output_tokens,
            cached_input_tokens=ev.cached_input_tokens,
            reasoning_tokens=ev.reasoning_tokens,
            latency_ms=ev.latency_ms, status=ev.status,
            provider_request_id=ev.provider_request_id,
            cost_reported_usd=ev.cost_reported_usd,
            cost_calculated_usd=calculated,
            meta=ev.metadata,
        ))
    db.add_all(rows)
    db.commit()
    return schemas.IngestEventsResponse(
        ingested=len(rows), unpriced=unpriced, total_calculated_usd=total)
