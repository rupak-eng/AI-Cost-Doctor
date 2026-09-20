"""SQLAlchemy models — schema per specs/02-architecture.md §3 plus `tenants`.

Conventions:
- Every tenant table carries `org_id` (UUID FK → organizations).
- Money uses Numeric (exact Decimal), never Float.
- Primary keys are UUIDs generated client-side (uuid4).
- Postgres RLS policies (migration 002) enforce org isolation as defense in
  depth; the app additionally scopes every query by org_id.

SQLite compatibility notes (tests only): CITEXT → String, JSONB → JSON via
with_variant; Uuid renders as CHAR(32) on SQLite.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _now():
    return func.now()


# citext on Postgres (case-insensitive unique email); plain String on SQLite.
EmailType = CITEXT().with_variant(String(255), "sqlite")
# JSONB on Postgres; generic JSON on SQLite.
JsonType = JSONB().with_variant(JSON(), "sqlite")

# Money columns: 8 decimal places — per-event costs can be fractions of a
# cent (e.g. 4k input tokens @ $2/1M = $0.008); aggregates stay exact.
COST = Numeric(20, 8)
REVENUE = Numeric(12, 2)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())

    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(EmailType, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="member")  # owner|admin|member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())

    organization: Mapped[Organization] = relationship(back_populates="users")


class RefreshToken(Base):
    """SHA-256 hashes of opaque refresh tokens. Rotation: revoked on use."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())

    organization: Mapped[Organization] = relationship(back_populates="projects")


class Tenant(Base):
    """A customer/tenant of the B2B SaaS user — the unit-economics spearhead.

    usage_events.tenant_id references tenants.external_id (text, not a hard
    FK: events may arrive before the tenant row exists via CSV/API).
    """

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("org_id", "external_id", name="uq_tenants_org_external"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL = revenue unknown (e.g. tenant auto-created from an event/CSV
    # before revenue was provided) → P&L margin is None, status 'unknown'.
    # This is deliberately distinct from 0, which would also be 'unknown'
    # per the status rule but would misread as "measured zero revenue".
    monthly_revenue_usd: Mapped[Decimal | None] = mapped_column(REVENUE, nullable=True, default=None)
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ProviderCredential(Base):
    """Provider API keys. Key material is NEVER stored in plaintext —
    only Fernet-encrypted bytes plus the last 4 chars for display."""

    __tablename__ = "provider_credentials"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)  # openai|anthropic|...
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")  # active|error
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ProviderCostReport(Base):
    """Provider-reported cost buckets, kept SEPARATE from usage events.

    Rationale: neither OpenAI's /organization/costs nor Anthropic's
    /cost_report breaks reported dollars down by model, so reported cost
    cannot be joined to per-model token rows without inventing an
    allocation. These rows are org-level reconciliation evidence
    ("the provider says $X for this bucket"); per-model economics always
    come from usage_events.cost_calculated_usd (deterministic catalog math).
    """

    __tablename__ = "provider_cost_reports"
    __table_args__ = (
        Index("ix_provider_cost_reports_org_time", "org_id", "bucket_start"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)  # openai|anthropic
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_width: Mapped[str] = mapped_column(Text, nullable=False, default="1d")
    # Grouping key as reported by the provider: OpenAI line_item,
    # Anthropic description. Stored verbatim — never parsed for models.
    group_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_usd: Mapped[Decimal] = mapped_column(COST, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    # Raw provider result object, for debugging shape drift in provider APIs.
    meta: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)


class ApiKey(Base):
    """Per-project event-ingest keys. Stored as SHA-256 hash ONLY."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True)  # for display
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelPrice(Base):
    """Versioned pricing catalog. Cost is always computed with the price
    row effective at the event's timestamp. Global (not org-scoped)."""

    __tablename__ = "model_prices"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_usd_per_1m: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    output_usd_per_1m: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    cached_input_usd_per_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    reasoning_usd_per_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(Date, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(Date, nullable=True)  # null = current
    source: Mapped[str] = mapped_column(Text, nullable=False, default="catalog")  # catalog|override

    __table_args__ = (
        Index("ix_model_prices_lookup", "provider", "model", "effective_from"),
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_org_time", "org_id", "occurred_at"),
        Index("ix_usage_events_org_project_time", "org_id", "project_id", "occurred_at"),
        Index("ix_usage_events_org_tenant_time", "org_id", "tenant_id", "occurred_at"),
        Index("ix_usage_events_org_model_time", "org_id", "model", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # event_api|csv|openai|anthropic
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    application: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str] = mapped_column(Text, nullable=False, default="production")
    tenant_id: Mapped[str | None] = mapped_column(Text, nullable=True)  # → tenants.external_id
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ok")  # ok|error
    provider_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the provider reported (if any) vs our deterministic catalog math.
    cost_reported_usd: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    cost_calculated_usd: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class CostAnomaly(Base):
    __tablename__ = "cost_anomalies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    dimension: Mapped[str] = mapped_column(Text, nullable=False)  # overall|provider|model|application|tenant
    dimension_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric: Mapped[str] = mapped_column(Text, nullable=False, default="cost_usd")
    baseline_usd: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    observed_usd: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    abs_delta_usd: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="info")  # info|warning|critical
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")  # open|investigated|resolved|dismissed|acknowledged
    # Which deterministic detector produced this row (Phase 6):
    # spend_spike | new_expensive_model | margin_killer_emergence
    detector: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Idempotency key — refresh-on-read detection never inserts twice for
    # the same fingerprint while a non-terminal row exists.
    fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # model_routing|prompt_caching|token_hygiene|...
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    current_cost_usd_mo: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    est_savings_usd_mo: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    confidence: Mapped[str] = mapped_column(Text, nullable=False, default="low")  # high|medium|low
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")  # open|applied|dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)  # slack|email
    config: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    anomaly_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_anomalies.id", ondelete="SET NULL"), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
