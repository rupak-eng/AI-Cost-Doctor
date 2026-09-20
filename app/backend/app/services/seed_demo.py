"""Deterministic synthetic demo dataset ("DemoCo").

Every figure in the demo is computed by the real cost engine
(`services/costing.py`) over the events generated here — no hardcoded P&L
numbers anywhere. The RNG is seeded, so re-seeding produces byte-identical
economics (modulo wall-clock timestamps).

Calibration targets (asserted ±5% in tests):
  Customer A  revenue $499/mo, AI cost ~$681/mo, margin ~-$182  -> margin_killer
  Customer B  revenue $299/mo, AI cost ~$247/mo, margin ~+$52   -> healthy
  Customer C  revenue $799/mo, AI cost ~$741/mo, margin ~+$58   -> at_risk [*]

[*] The binding status rule (spec 03 API contract) is at_risk iff
margin < 15% of revenue. $58 < 0.15 x $799, so C is at_risk. All three
statuses are represented in the demo, which is good for the narrative.

Customer A recipe (documented deviation from the draft recipe):
  The binding recommendation rule (services/recommend.py) estimates savings
  as per-token price delta x pair tokens x 50% shiftable share. For the
  headline "route Classification gpt-4.1 -> gpt-4.1-mini saves ~$140/mo"
  story to hold under that rule, the Classification pair must cost ~$350/mo
  (0.5 x 0.8 x 350 = 140). It is therefore seeded at ~64.8k req/mo
  ($350/mo); Support Agent consequently represents ~47% of Customer A's AI
  cost rather than the draft recipe's ~73%. The gpt-4.1 share of Support
  Agent spend (~81%) is preserved. All asserted calibration targets hold.

Customer A also gets mild deterministic growth over the last 7 days so that
Investigate can report a volume (not token) change.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as m
from app.core.config import settings
from app.services import costing

SEED = 20260921
WINDOW_DAYS = 30
SOURCE = "event_api"


def _pin_demo_rls(db: Session) -> None:
    """Pin the RLS org context to the demo org (no-op on non-Postgres).

    Makes seed/reset self-sufficient for direct callers (tests, scripts);
    the HTTP endpoints set the same context before calling.
    """
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(demo_org_id())})


def demo_org_id() -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{settings.demo_namespace}/org/democo")


def demo_project_id() -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{settings.demo_namespace}/project/democo-prod")


@dataclass(frozen=True)
class TrafficProfile:
    tenant_external_id: str
    tenant_name: str
    monthly_revenue_usd: Decimal
    plan: str
    application: str
    provider: str
    model: str
    avg_input_tokens: int
    avg_output_tokens: int
    monthly_requests: int
    growth_last_7d: bool = False


# (tenant, app, provider, model, token profile, monthly requests)
PROFILES: list[TrafficProfile] = [
    # --- Customer A ------------------------------------------------------
    TrafficProfile("cust-a", "Customer A", Decimal("499"), "scale",
                   "Support Agent", "openai", "gpt-4.1", 4000, 1000, 16_375, True),
    TrafficProfile("cust-a", "Customer A", Decimal("499"), "scale",
                   "Support Agent", "openai", "gpt-4.1-mini", 4000, 1000, 19_062, True),
    TrafficProfile("cust-a", "Customer A", Decimal("499"), "scale",
                   "Classification", "openai", "gpt-4.1", 1500, 300, 64_815, True),
    TrafficProfile("cust-a", "Customer A", Decimal("499"), "scale",
                   "Summarization", "openai", "gpt-4.1-mini", 2000, 500, 5_000, True),
    # --- Customer B ------------------------------------------------------
    TrafficProfile("cust-b", "Customer B", Decimal("299"), "growth",
                   "Doc Q&A", "openai", "gpt-4.1-mini", 6000, 2000, 44_107),
    # --- Customer C ------------------------------------------------------
    TrafficProfile("cust-c", "Customer C", Decimal("799"), "enterprise",
                   "Code Assistant", "openai", "gpt-4.1", 6000, 1500, 25_729),
    TrafficProfile("cust-c", "Customer C", Decimal("799"), "enterprise",
                   "Code Assistant", "anthropic", "claude-3-5-haiku-20241022", 4000, 1000, 17_153),
]

TENANTS = [
    ("cust-a", "Customer A", Decimal("499"), "scale"),
    ("cust-b", "Customer B", Decimal("299"), "growth"),
    ("cust-c", "Customer C", Decimal("799"), "enterprise"),
]


def _growth_multiplier(day_index: int) -> float:
    """Mild deterministic ramp over the last 7 days (day_index 23..29)."""
    if day_index < WINDOW_DAYS - 7:
        return 1.0
    return 1.0 + 0.04 * (day_index - (WINDOW_DAYS - 8))


def _growth_sum() -> float:
    return sum(_growth_multiplier(d) for d in range(WINDOW_DAYS))


def seed_demo_org(db: Session) -> dict:
    """Create the DemoCo org + project + tenants + 30d of usage events.

    Idempotent guard: raises ValueError if the demo org already exists
    (call reset_demo_org first).
    """
    org_id = demo_org_id()
    _pin_demo_rls(db)
    if db.get(m.Organization, org_id) is not None:
        raise ValueError("demo dataset already seeded — call DELETE /demo/reset first")

    catalog = costing.load_catalog()
    costing.ensure_catalog_in_db(db, catalog)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS) + timedelta(hours=1)

    org = m.Organization(id=org_id, name="DemoCo", slug="democo", plan="growth")
    db.add(org)
    project_id = demo_project_id()
    # NOTE: associate via the ORM relationship, not the raw FK column.
    # Organization.projects carries a delete-orphan cascade; on PostgreSQL,
    # SQLAlchemy 2.0.54's unit of work silently discards a *pending* child that
    # is only linked by FK column (treats it as an orphan) when parent and
    # child are flushed together. Using the relationship keeps the INSERT.
    project = m.Project(id=project_id, organization=org, name="DemoCo Production")
    db.add(project)
    # Flush org + project before tenants: tenants reference the project via
    # raw FK columns (no relationship), which is safe once the project row
    # is persistent.
    db.flush()
    for external_id, name, revenue, plan in TENANTS:
        db.add(m.Tenant(org_id=org_id, project_id=project_id, external_id=external_id,
                        name=name, monthly_revenue_usd=revenue, plan=plan))
    db.flush()

    rng = random.Random(SEED)
    growth_sum = _growth_sum()
    rows: list[dict] = []
    for p in PROFILES:
        price = costing.price_for(catalog, provider=p.provider, model=p.model, at=now)
        base_daily = p.monthly_requests / (growth_sum if p.growth_last_7d else WINDOW_DAYS)
        for day in range(WINDOW_DAYS):
            mult = _growth_multiplier(day) if p.growth_last_7d else 1.0
            n = round(base_daily * mult * (1.0 + rng.uniform(-0.06, 0.06)))
            day_start = window_start + timedelta(days=day)
            for _ in range(max(n, 0)):
                in_tok = max(1, round(p.avg_input_tokens * (1.0 + rng.uniform(-0.10, 0.10))))
                out_tok = max(1, round(p.avg_output_tokens * (1.0 + rng.uniform(-0.10, 0.10))))
                occurred = day_start + timedelta(seconds=rng.randint(0, 86_399))
                cost = costing.event_cost(input_tokens=in_tok, output_tokens=out_tok, price=price)
                rows.append({
                    "id": uuid.uuid4(),
                    "org_id": org_id,
                    "project_id": project_id,
                    "source": SOURCE,
                    "provider": p.provider,
                    "model": p.model,
                    "application": p.application,
                    "environment": "production",
                    "tenant_id": p.tenant_external_id,
                    "occurred_at": occurred,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "cached_input_tokens": 0,
                    "reasoning_tokens": 0,
                    "latency_ms": rng.randint(400, 4000),
                    "status": "ok",
                    "provider_request_id": None,
                    "cost_reported_usd": None,
                    "cost_calculated_usd": cost,
                    "meta": {},
                })
        # (loop continues over profiles)

    # Bulk insert in chunks (keeps memory flat at ~190k rows).
    for i in range(0, len(rows), 5_000):
        db.bulk_insert_mappings(m.UsageEvent, rows[i:i + 5_000])
    db.commit()
    return {
        "org_id": str(org_id),
        "project_id": str(project_id),
        "tenants": [t[0] for t in TENANTS],
        "events": len(rows),
        "data_label": "demo",
    }


def reset_demo_org(db: Session) -> dict:
    """Delete the DemoCo org and everything under it. Explicit deletes in
    dependency order (RLS-friendly: every statement is org-scoped)."""
    org_id = demo_org_id()
    _pin_demo_rls(db)
    org = db.get(m.Organization, org_id)
    if org is None:
        return {"deleted": False, "data_label": "demo"}
    db.query(m.UsageEvent).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.Tenant).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.ApiKey).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.ProviderCredential).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.RefreshToken).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.AlertEvent).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.Alert).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.Recommendation).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.CostAnomaly).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.AuditLog).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.Project).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.User).filter_by(org_id=org_id).delete(synchronize_session=False)
    db.query(m.Organization).filter_by(id=org_id).delete(synchronize_session=False)
    # Bulk deletes bypass the identity map: expire everything so a subsequent
    # db.get() in the same session sees the rows as gone, not as ghosts.
    db.expire_all()
    db.commit()
    return {"deleted": True, "data_label": "demo"}
