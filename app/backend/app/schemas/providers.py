"""Provider connection schemas (POST /integrations/providers, JWT auth)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProviderName = Literal["openai", "anthropic"]


class ProviderConnectRequest(BaseModel):
    provider: ProviderName
    api_key: str = Field(min_length=8, max_length=500)
    label: str | None = Field(default=None, max_length=120)


class ProviderCredentialInfo(BaseModel):
    id: str
    provider: str
    label: str | None
    key_last4: str | None
    status: str
    last_sync_at: datetime | None


class ProviderSyncRequest(BaseModel):
    days_back: int = Field(default=30, ge=1, le=90)
    extra_group_by: list[str] = Field(default_factory=list, max_length=8)


class ProviderSyncResponse(BaseModel):
    provider: str
    project_id: str
    window_start: str
    window_end: str
    usage_buckets: int
    events_written: int
    cost_reports_written: int
    unpriced_models: list[str]
    notes: list[str]
