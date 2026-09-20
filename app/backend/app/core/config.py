"""Application settings, read from the environment.

No pydantic-settings dependency on purpose: plain stdlib parsing keeps the
container image small and the behaviour obvious.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _get(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_cost_doctor"))
    jwt_secret: str = field(default_factory=lambda: _get("JWT_SECRET", "dev-only-insecure-secret"))
    jwt_algorithm: str = field(default_factory=lambda: _get("JWT_ALGORITHM", "HS256"))
    access_token_expire_minutes: int = field(default_factory=lambda: _get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    refresh_token_expire_days: int = field(default_factory=lambda: _get_int("REFRESH_TOKEN_EXPIRE_DAYS", 30))
    fernet_key: str = field(default_factory=lambda: _get("FERNET_KEY", ""))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in _get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()))
    demo_namespace: str = field(default_factory=lambda: _get("DEMO_NAMESPACE", "ai-cost-doctor-demo"))
    environment: str = field(default_factory=lambda: _get("ENVIRONMENT", "development"))
    # Optional narrative polish for /investigate/explain. Unset by default:
    # the template narrative is always used unless a key is provided.
    narrative_llm_api_key: str = field(default_factory=lambda: _get("NARRATIVE_LLM_API_KEY", ""))
    narrative_llm_model: str = field(default_factory=lambda: _get("NARRATIVE_LLM_MODEL", "gpt-4o-mini"))
    narrative_llm_base_url: str = field(default_factory=lambda: _get("NARRATIVE_LLM_BASE_URL", "https://api.openai.com/v1"))


settings = Settings()
