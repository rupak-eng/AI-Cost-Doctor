"""Billing response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlanLimitsOut(BaseModel):
    display_name: str
    monthly_price_usd: int
    max_projects: int
    events_per_month: int
    retention_days: int


class BillingStatusOut(BaseModel):
    plan: str
    effective_plan: str
    subscription_status: str | None
    trial_active: bool
    trial_days_left: int | None
    trial_ends_at: datetime | None
    has_paid_access: bool
    stripe_customer_id: str | None
    limits: PlanLimitsOut
    projects_count: int
    events_this_month: int
    events_over_limit: bool
    stripe_configured: bool
    data_label: str = "customer"


class CheckoutRequest(BaseModel):
    plan: str = Field(description='One of "starter", "growth"')


class CheckoutResponse(BaseModel):
    url: str
    session_id: str
    reused: bool = False
    data_label: str = "customer"


class PortalResponse(BaseModel):
    url: str
    data_label: str = "customer"


class WebhookResponse(BaseModel):
    received: bool = True
    handled: bool = False
    duplicate: bool = False
