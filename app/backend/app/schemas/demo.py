"""Demo API response schemas. Every response carries data_label="demo"."""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class PnLRow(BaseModel):
    tenant_id: uuid.UUID
    tenant_external_id: str
    name: str
    revenue_usd: Decimal
    ai_cost_usd: Decimal
    margin_usd: Decimal
    status: str = Field(pattern="^(margin_killer|at_risk|healthy)$")


class PnLResponse(BaseModel):
    data_label: str = "demo"
    tenants: list[PnLRow]


class InvestigateRequest(BaseModel):
    tenant_external_id: str = Field(min_length=1)


class ModelCostDriver(BaseModel):
    """Cost driver keyed by model — contract: by_model: [{model, cost_usd, pct}]."""
    model: str
    cost_usd: Decimal
    pct: float


class AppCostDriver(BaseModel):
    """Cost driver keyed by application — contract: by_app: [{app, cost_usd, pct}]."""
    app: str
    cost_usd: Decimal
    pct: float


class Drivers(BaseModel):
    by_model: list[ModelCostDriver]
    by_app: list[AppCostDriver]


class ExpensiveWorkflow(BaseModel):
    app: str
    model: str
    requests: int
    cost_usd: Decimal
    cost_per_request_usd: Decimal


class VolumeVsTokens(BaseModel):
    requests_delta_pct: float
    avg_tokens_per_request_delta_pct: float
    window_note: str = "last 7 days vs prior 23 days"
    # Dollar attribution of the cost change (recent 7d vs prior window):
    # request-count change alone, tokens/request change alone, and the
    # residual model/price-mix effect. None when there is no prior window.
    volume_effect_usd: Decimal | None = None
    token_intensity_effect_usd: Decimal | None = None
    mix_effect_usd: Decimal | None = None


class RecommendationOut(BaseModel):
    type: str = "model_routing"  # model_routing | prompt_caching | anomaly_followup
    title: str = ""
    action: str
    explanation: str = ""
    est_savings_usd_mo: Decimal
    confidence: str = Field(pattern="^(high|medium|low)$")
    post_change_margin_usd: Decimal | None = None
    detail: dict = {}
    disclaimer: str = "Estimates are not guarantees."


class InvestigateResponse(BaseModel):
    data_label: str = "demo"
    tenant_external_id: str
    tenant_name: str
    summary: str
    margin_usd: Decimal | None = None
    drivers: Drivers
    volume_vs_tokens: VolumeVsTokens
    expensive_workflows: list[ExpensiveWorkflow]
    recommendation: RecommendationOut | None
    recommendations: list[RecommendationOut] = []
    disclaimer: str = "Estimates are not guarantees."
