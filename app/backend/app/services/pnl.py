"""Per-tenant P&L aggregation — the shared engine behind both the demo P&L
and the customer project P&L.

Rule (spec 03 API contract, binding): for each tenant over the window,
  ai_cost = SUM(usage_events.cost_calculated_usd)
  margin  = revenue - ai_cost            (None when revenue is unknown)
  status  = margin_killer  if margin < 0
            at_risk        if margin < 15% of revenue
            healthy        otherwise
            unknown        if revenue is NULL or 0 (margin then None)

Nothing here hardcodes a figure — every number aggregates usage events.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app import models as m


def tenant_status(margin_usd: Decimal | None, revenue_usd: Decimal | None) -> str:
    """Binding status rule. Revenue NULL/0 means the tenant's unit economics
    are not yet measurable → margin None, status 'unknown'."""
    if revenue_usd is None or revenue_usd == 0:
        return "unknown"
    if margin_usd is None:  # defensive: margin is always set when revenue is
        return "unknown"
    if margin_usd < 0:
        return "margin_killer"
    if margin_usd < Decimal("0.15") * revenue_usd:
        return "at_risk"
    return "healthy"


def _tenant_costs(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                  start: datetime, end: datetime) -> dict[str, tuple[int, Decimal, int]]:
    """{tenant_external_id: (requests, cost_usd, unpriced_events)} over the window.

    Unpriced events (NULL calculated cost) are counted per tenant so a tenant
    whose cost is unknown is never silently presented as costing $0.
    """
    rows = (
        db.query(
            m.UsageEvent.tenant_id,
            func.count(m.UsageEvent.id),
            func.sum(m.UsageEvent.cost_calculated_usd),
            func.sum(case((m.UsageEvent.cost_calculated_usd.is_(None), 1), else_=0)),
        )
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= start,
            m.UsageEvent.occurred_at < end,
        )
        .group_by(m.UsageEvent.tenant_id)
        .all()
    )
    return {r[0]: (r[1], r[2] or Decimal(0), r[3] or 0) for r in rows}


def _window(days: int, end: datetime | None = None) -> tuple[datetime, datetime]:
    end = end or datetime.now(timezone.utc)
    return end - timedelta(days=days), end


def compute_pnl_for_window(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                           start: datetime, end: datetime) -> list[dict]:
    """Per-tenant P&L rows for an explicit [start, end) window.

    Same rule as compute_pnl; factored out so detectors (e.g. anomaly
    detection comparing consecutive windows) reuse the identical math.
    """
    costs = _tenant_costs(db, org_id, project_id, start, end)
    tenants = (
        db.query(m.Tenant)
        .filter_by(org_id=org_id, project_id=project_id)
        .order_by(m.Tenant.external_id)
        .all()
    )
    rows = []
    for t in tenants:
        _, cost, unpriced = costs.get(t.external_id, (0, Decimal(0), 0))
        revenue = t.monthly_revenue_usd  # None = unknown (e.g. auto-created via ingest)
        margin = (revenue - cost) if revenue is not None and revenue != 0 else None
        rows.append({
            "tenant_id": t.id,
            "tenant_external_id": t.external_id,
            "name": t.name,
            "revenue_usd": revenue,
            "ai_cost_usd": cost,
            "unpriced_events": unpriced,
            "margin_usd": margin,
            "status": tenant_status(margin, revenue),
        })
    return rows


def compute_pnl(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                days: int = 30) -> list[dict]:
    """Per-tenant P&L rows for a project over the trailing `days`.

    Returns a list of dicts with keys:
      tenant_id, tenant_external_id, name, revenue_usd,
      ai_cost_usd, unpriced_events, margin_usd (None when revenue unknown), status.
    Tenants with no events in the window still appear (cost 0).
    """
    start, end = _window(days)
    return compute_pnl_for_window(db, org_id, project_id, start, end)
