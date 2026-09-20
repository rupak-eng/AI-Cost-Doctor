"""Project API key schemas. The plaintext secret is returned exactly once,
at creation; listings never include it."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str | None
    api_key: str  # plaintext — shown ONCE, never stored
    created_at: datetime


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    key_prefix: str | None
    created_at: datetime
    revoked_at: datetime | None
