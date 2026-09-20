"""Event-ingest schemas (POST /ingest/events, X-API-Key auth)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class UsageEventIn(BaseModel):
    occurred_at: datetime
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=500)
    application: str | None = Field(default=None, max_length=500)
    environment: str = Field(default="production", max_length=100)
    tenant_id: str | None = Field(default=None, max_length=500)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    status: str = Field(default="ok", max_length=50)
    provider_request_id: str | None = Field(default=None, max_length=500)
    cost_reported_usd: Decimal | None = None
    metadata: dict = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        # Naive timestamps are assumed UTC (contract: ISO-8601 UTC).
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)


class IngestEventsRequest(BaseModel):
    events: list[UsageEventIn] = Field(min_length=1, max_length=1000)


class IngestEventsResponse(BaseModel):
    ingested: int
    unpriced: int  # events stored with cost_calculated_usd NULL (no catalog price)
    total_calculated_usd: Decimal
