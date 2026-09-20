"""Dashboard aggregations for a customer project.

Every figure in the dashboard is an aggregation over usage_events — no
pricing math happens here. Per-event costs are written by the deterministic
cost engine (app.services.costing) at ingest/sync time into
usage_events.cost_calculated_usd, so this module only SUMs and COUNTs.

Cost basis is therefore always "calculated" (deterministic catalog math).
Provider-reported numbers are deliberately excluded from the dashboard —
they live in provider_cost_reports and are daily-only, so mixing them into
per-model/per-application breakdowns would invent an attribution.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models as m

COST_BASIS = "calculated"
UNSPECIFIED_APPLICATION = "Unspecified"


def _window(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


def _base_query(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                start: datetime, end: datetime):
    return (
        db.query(m.UsageEvent)
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= start,
            m.UsageEvent.occurred_at < end,
        )
    )


def compute_dashboard(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                       days: int = 30) -> dict:
    """Aggregate dashboard figures for a project over the trailing `days`.

    Returns a dict with keys: days, total_cost_usd, total_requests,
    unpriced_events, cost_basis, trend (per-day cost/requests), by_model,
    by_application, top_tenants. All cost values are Decimal.
    """
    start, end = _window(days)
    q = _base_query(db, org_id, project_id, start, end)

    total_cost = q.with_entities(
        func.coalesce(func.sum(m.UsageEvent.cost_calculated_usd), 0)).scalar() or Decimal(0)
    total_cost = Decimal(total_cost)
    total_requests = q.count()
    unpriced_events = q.filter(m.UsageEvent.cost_calculated_usd.is_(None)).count()

    trend = _trend(q, start, end)
    by_model = _by_model(db, org_id, project_id, start, end, total_cost)
    by_application = _by_application(db, org_id, project_id, start, end, total_cost)
    top_tenants = _top_tenants(db, org_id, project_id, start, end)

    return {
        "days": days,
        "total_cost_usd": total_cost,
        "total_requests": total_requests,
        "unpriced_events": unpriced_events,
        "cost_basis": COST_BASIS,
        "trend": trend,
        "by_model": by_model,
        "by_application": by_application,
        "top_tenants": top_tenants,
    }


def _trend(q, start: datetime, end: datetime) -> list[dict]:
    """Per-day (UTC) cost/request buckets, zero-filled across the window.

    Bucketing is done in Python (not SQL date-trunc) so behaviour is
    identical on PostgreSQL and SQLite.
    """
    days = (end.date() - start.date()).days + 1
    buckets: dict[str, dict] = {}
    for i in range(days):
        key = (start.date() + timedelta(days=i)).isoformat()
        buckets[key] = {"date": key, "cost_usd": Decimal(0), "requests": 0}
    rows = q.with_entities(m.UsageEvent.occurred_at,
                           m.UsageEvent.cost_calculated_usd).all()
    for occurred_at, cost in rows:
        key = occurred_at.date().isoformat()
        bucket = buckets.get(key)
        if bucket is None:  # defensive: event outside the window
            continue
        bucket["requests"] += 1
        bucket["cost_usd"] += cost or Decimal(0)
    return [buckets[k] for k in sorted(buckets)]


def _share(cost: Decimal, total: Decimal) -> Decimal:
    if total == 0:
        return Decimal(0)
    return (cost / total * 100).quantize(Decimal("0.1"))


def _by_model(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
              start: datetime, end: datetime, total_cost: Decimal) -> list[dict]:
    rows = (
        db.query(
            m.UsageEvent.provider,
            m.UsageEvent.model,
            func.coalesce(func.sum(m.UsageEvent.cost_calculated_usd), 0),
            func.count(m.UsageEvent.id),
        )
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= start,
            m.UsageEvent.occurred_at < end,
        )
        .group_by(m.UsageEvent.provider, m.UsageEvent.model)
        .order_by(func.coalesce(func.sum(m.UsageEvent.cost_calculated_usd), 0).desc())
        .all()
    )
    return [
        {
            "provider": provider,
            "model": model,
            "cost_usd": Decimal(cost),
            "requests": requests,
            "share_pct": _share(Decimal(cost), total_cost),
        }
        for provider, model, cost, requests in rows
    ]


def _by_application(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                    start: datetime, end: datetime,
                    total_cost: Decimal) -> list[dict]:
    rows = (
        db.query(
            m.UsageEvent.application,
            func.coalesce(func.sum(m.UsageEvent.cost_calculated_usd), 0),
            func.count(m.UsageEvent.id),
        )
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= start,
            m.UsageEvent.occurred_at < end,
        )
        .group_by(m.UsageEvent.application)
        .order_by(func.coalesce(func.sum(m.UsageEvent.cost_calculated_usd), 0).desc())
        .all()
    )
    return [
        {
            "application": application or UNSPECIFIED_APPLICATION,
            "cost_usd": Decimal(cost),
            "requests": requests,
            "share_pct": _share(Decimal(cost), total_cost),
        }
        for application, cost, requests in rows
    ]


def _top_tenants(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                 start: datetime, end: datetime, limit: int = 10) -> list[dict]:
    rows = (
        db.query(
            m.UsageEvent.tenant_id,
            func.coalesce(func.sum(m.UsageEvent.cost_calculated_usd), 0),
            func.count(m.UsageEvent.id),
        )
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= start,
            m.UsageEvent.occurred_at < end,
        )
        .group_by(m.UsageEvent.tenant_id)
        .order_by(func.coalesce(func.sum(m.UsageEvent.cost_calculated_usd), 0).desc())
        .limit(limit)
        .all()
    )
    names = {
        t.external_id: t.name
        for t in db.query(m.Tenant).filter_by(org_id=org_id, project_id=project_id).all()
    }
    return [
        {
            "tenant_external_id": tenant_id,
            "tenant_name": names.get(tenant_id),
            "cost_usd": Decimal(cost),
            "requests": requests,
        }
        for tenant_id, cost, requests in rows
    ]
