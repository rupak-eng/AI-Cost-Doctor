"""Customer project P&L / investigate schemas.

Same shapes as the demo responses, but data_label="customer", and revenue /
margin are nullable (status may be "unknown" when revenue isn't known yet).
Sub-schemas are shared with the demo module — the engine output is identical.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.demo import (
    Drivers,
    ExpensiveWorkflow,
    RecommendationOut,
    VolumeVsTokens,
)


class ProjectPnLRow(BaseModel):
    tenant_id: uuid.UUID
    tenant_external_id: str
    name: str
    revenue_usd: Decimal | None
    ai_cost_usd: Decimal
    margin_usd: Decimal | None
    status: str = Field(pattern="^(margin_killer|at_risk|healthy|unknown)$")


class ProjectPnLResponse(BaseModel):
    data_label: str = "customer"
    tenants: list[ProjectPnLRow]


class ProjectInvestigateRequest(BaseModel):
    tenant_external_id: str = Field(min_length=1)


class CustomerRecommendationOut(RecommendationOut):
    # post_change_margin_usd is None when the tenant has no recorded revenue.
    post_change_margin_usd: Decimal | None


class ProjectInvestigateResponse(BaseModel):
    data_label: str = "customer"
    tenant_external_id: str
    tenant_name: str
    summary: str
    drivers: Drivers
    volume_vs_tokens: VolumeVsTokens
    expensive_workflows: list[ExpensiveWorkflow]
    recommendation: CustomerRecommendationOut | None


class DashboardTrendPoint(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    cost_usd: Decimal
    requests: int


class DashboardModelRow(BaseModel):
    provider: str
    model: str
    cost_usd: Decimal
    requests: int
    share_pct: Decimal  # share of total calculated cost


class DashboardApplicationRow(BaseModel):
    application: str
    cost_usd: Decimal
    requests: int
    share_pct: Decimal  # share of total calculated cost


class DashboardTenantRow(BaseModel):
    tenant_external_id: str | None
    tenant_name: str | None
    cost_usd: Decimal
    requests: int


class ProjectDashboardResponse(BaseModel):
    data_label: str = "customer"
    days: int
    total_cost_usd: Decimal
    total_requests: int
    unpriced_events: int
    cost_basis: str = "calculated"  # every figure is deterministic catalog math
    trend: list[DashboardTrendPoint]
    by_model: list[DashboardModelRow]
    by_application: list[DashboardApplicationRow]
    top_tenants: list[DashboardTenantRow]
