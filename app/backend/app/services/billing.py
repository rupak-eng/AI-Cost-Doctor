"""Billing: plans, entitlements, Stripe checkout/portal/webhooks.

This module is the SINGLE place where paywall decisions are made —
endpoints call :func:`require_paid_feature` / :func:`check_project_limit`
and nothing else. All dollar math stays in the cost engine; Stripe is only
the payment rail.

Plans (flat monthly, no usage-based billing in v0.1):
  free     $0    — 1 project, 100k events/mo, 30d retention
  starter  $49   — 1 project, 1M events/mo, 30d retention
  growth   $199  — 5 projects, 10M events/mo, 365d retention
Trial: 14 days, cardless, full (growth-level) features. Modeled as
``organizations.trial_ends_at`` — not a Stripe object — so no Stripe objects
exist during trial.

Event counts are metered for SOFT limit warnings only (never hard-blocked).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import stripe
from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.core.config import settings
from app.services import stripe_client

TRIAL_DAYS = 14

# Subscription statuses that keep paid access (past_due = grace period).
PAID_SUBSCRIPTION_STATUSES = frozenset({"trialing", "active", "past_due"})

PLANS: dict[str, dict] = {
    "free": {
        "display_name": "Free",
        "monthly_price_usd": 0,
        "max_projects": 1,
        "events_per_month": 100_000,
        "retention_days": 30,
    },
    "starter": {
        "display_name": "Starter",
        "monthly_price_usd": 49,
        "max_projects": 1,
        "events_per_month": 1_000_000,
        "retention_days": 30,
    },
    "growth": {
        "display_name": "Growth",
        "monthly_price_usd": 199,
        "max_projects": 5,
        "events_per_month": 10_000_000,
        "retention_days": 365,
    },
}

PAID_PLANS = ("starter", "growth")

# Feature -> minimum access level. "paid" = active trial OR paid subscription.
FEATURE_MIN_ACCESS: dict[str, str] = {
    "provider_sync": "paid",   # Phase 4 connectors: pull from OpenAI/Anthropic
    "anomaly_reads": "paid",   # Phase 6 anomaly feed
}
# Free tier keeps: demo, CSV ingestion, dashboard, P&L, investigate.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes (SQLite test backend drops tzinfo).

    Production runs Postgres timestamptz where values are already aware;
    without this, trial comparisons would TypeError on SQLite.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def trial_active(org: m.Organization, now: datetime | None = None) -> bool:
    now = now or _utcnow()
    ends = _aware(org.trial_ends_at)
    return ends is not None and ends > now


def trial_days_left(org: m.Organization, now: datetime | None = None) -> int | None:
    now = now or _utcnow()
    ends = _aware(org.trial_ends_at)
    if ends is None or ends <= now:
        return None
    return max(0, int((ends - now).total_seconds() // 86400))


def subscription_paid(org: m.Organization) -> bool:
    return (org.subscription_status or "") in PAID_SUBSCRIPTION_STATUSES


def has_paid_access(org: m.Organization, now: datetime | None = None) -> bool:
    """Trial (cardless) or a paid Stripe subscription in good standing."""
    return trial_active(org, now) or subscription_paid(org)


def effective_plan(org: m.Organization, now: datetime | None = None) -> str:
    """Plan whose limits apply: paid plan > trial (full features) > free."""
    now = now or _utcnow()
    if subscription_paid(org) and org.plan in PAID_PLANS:
        return org.plan
    if trial_active(org, now):
        return "growth"  # trial = full features
    return "free"


def plan_limits(plan: str) -> dict:
    return PLANS.get(plan, PLANS["free"])


def _get_org(db: Session, org_id: uuid.UUID) -> m.Organization:
    org = db.get(m.Organization, org_id)
    if org is None:  # pragma: no cover - defensive; JWT orgs always exist
        raise HTTPException(status_code=404, detail="organization not found")
    return org


def require_paid_feature(user: m.User, db: Session, feature: str) -> m.Organization:
    """The paywall gate. Raises 402 when the org lacks paid access.

    Call at the top of every paid endpoint — keep ALL gating here so the
    paywall is auditable in one place.
    """
    if feature not in FEATURE_MIN_ACCESS:
        raise ValueError(f"unknown gated feature: {feature}")
    org = _get_org(db, user.org_id)
    if not has_paid_access(org):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"'{feature}' requires a trial or paid plan. "
                "Start your 14-day free trial or choose a plan at /app/billing."
            ),
        )
    return org


def check_project_limit(user: m.User, db: Session) -> m.Organization:
    """Raise 402 when the org is at its plan's project cap."""
    org = _get_org(db, user.org_id)
    limit = plan_limits(effective_plan(org))["max_projects"]
    count = db.query(func.count(m.Project.id)).filter_by(org_id=org.id).scalar() or 0
    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Project limit reached ({limit} on the "
                f"{plan_limits(effective_plan(org))['display_name']} plan). "
                "Upgrade at /app/billing to add more projects."
            ),
        )
    return org


def monthly_event_count(db: Session, org_id: uuid.UUID, now: datetime | None = None) -> int:
    """Events ingested by the org in the current calendar month (soft metering)."""
    now = now or _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(m.UsageEvent.id))
        .filter(m.UsageEvent.org_id == org_id,
                m.UsageEvent.occurred_at >= month_start)
        .scalar()
        or 0
    )


@dataclass
class BillingStatus:
    plan: str
    effective_plan: str
    subscription_status: str | None
    trial_active: bool
    trial_days_left: int | None
    trial_ends_at: datetime | None
    has_paid_access: bool
    stripe_customer_id: str | None
    limits: dict
    projects_count: int
    events_this_month: int
    events_over_limit: bool


def get_billing_status(db: Session, org_id: uuid.UUID) -> BillingStatus:
    org = _get_org(db, org_id)
    now = _utcnow()
    plan = effective_plan(org, now)
    limits = plan_limits(plan)
    events = monthly_event_count(db, org_id, now)
    projects = db.query(func.count(m.Project.id)).filter_by(org_id=org.id).scalar() or 0
    return BillingStatus(
        plan=org.plan,
        effective_plan=plan,
        subscription_status=org.subscription_status,
        trial_active=trial_active(org, now),
        trial_days_left=trial_days_left(org, now),
        trial_ends_at=_aware(org.trial_ends_at),
        has_paid_access=has_paid_access(org, now),
        stripe_customer_id=org.stripe_customer_id,
        limits=limits,
        projects_count=projects,
        events_this_month=events,
        events_over_limit=events > limits["events_per_month"],
    )


# --- Stripe operations -----------------------------------------------------

def price_id_for_plan(plan: str) -> str:
    if plan == "starter":
        return settings.stripe_price_starter
    if plan == "growth":
        return settings.stripe_price_growth
    raise ValueError(f"plan '{plan}' is not purchasable")


def plan_for_price_id(price_id: str | None) -> str | None:
    """Map a Stripe Price ID back to our plan (env-configured catalog)."""
    if price_id and price_id == settings.stripe_price_starter:
        return "starter"
    if price_id and price_id == settings.stripe_price_growth:
        return "growth"
    return None


def _frontend_url() -> str:
    return settings.frontend_url.rstrip("/")


def get_or_create_customer(db: Session, org: m.Organization,
                           owner_email: str, client=None) -> str:
    """Return the org's Stripe customer id, creating it (and persisting the
    id) when missing."""
    if org.stripe_customer_id:
        return org.stripe_customer_id
    client = client or stripe_client.get_stripe_client()
    customer = client.v1.customers.create(params={
        "email": owner_email,
        "name": org.name,
        "metadata": {"org_id": str(org.id)},
    })
    org.stripe_customer_id = customer["id"]
    db.add(org)
    db.flush()
    return org.stripe_customer_id


def _open_session_url(org: m.Organization, client, plan: str) -> str | None:
    """Return the still-open pending checkout URL for the SAME plan, if any.

    Idempotency is per (org, plan): an open Starter session is not reused
    for a Growth request — that would charge the wrong price.
    """
    if not org.stripe_pending_session_id:
        return None
    try:
        session = client.v1.checkout.sessions.retrieve(org.stripe_pending_session_id)
    except Exception:
        return None  # treat retrieval failure as "no usable session"
    meta = session.get("metadata") or {}
    if (session.get("status") == "open" and session.get("url")
            and meta.get("plan") == plan):
        return session["url"]
    return None


def create_checkout_session(db: Session, org: m.Organization, plan: str,
                            owner_email: str, client=None) -> dict:
    """Create (or reuse) a Stripe Checkout Session for a plan purchase.

    Idempotent per org: an existing still-open session is reused so
    double-clicks don't spawn duplicate checkouts.
    """
    if plan not in PAID_PLANS:
        raise ValueError(f"plan '{plan}' is not purchasable")
    price_id = price_id_for_plan(plan)
    if not price_id:
        raise RuntimeError(f"STRIPE_PRICE_{plan.upper()} is not configured")
    if not stripe_client.stripe_configured():
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
    client = client or stripe_client.get_stripe_client()

    if subscription_paid(org) and org.plan == plan:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="already subscribed to this plan — manage it via the billing portal")

    reuse = _open_session_url(org, client, plan)
    if reuse:
        return {"url": reuse, "session_id": org.stripe_pending_session_id, "reused": True}

    customer_id = get_or_create_customer(db, org, owner_email, client)
    base = _frontend_url()
    session = client.v1.checkout.sessions.create(params={
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{base}/app/billing?checkout=success",
        "cancel_url": f"{base}/app/billing?checkout=cancelled",
        "allow_promotion_codes": True,
        "metadata": {"org_id": str(org.id), "plan": plan},
        "subscription_data": {"metadata": {"org_id": str(org.id), "plan": plan}},
    })
    org.stripe_pending_session_id = session["id"]
    db.add(org)
    db.flush()
    return {"url": session["url"], "session_id": session["id"], "reused": False}


def create_portal_session(db: Session, org: m.Organization, client=None) -> dict:
    if not org.stripe_customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="no billing account yet — choose a plan first")
    if not stripe_client.stripe_configured():
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
    client = client or stripe_client.get_stripe_client()
    session = client.v1.billing_portal.sessions.create(params={
        "customer": org.stripe_customer_id,
        "return_url": f"{_frontend_url()}/app/billing",
    })
    return {"url": session["url"]}


# --- Webhooks --------------------------------------------------------------

def _bootstrap_org_lookup(db: Session):
    """Narrow RLS bootstrap for resolving an org by Stripe customer id before
    any org context exists — mirrors deps.pre_auth_lookup (organizations
    policy allows the bootstrap; see migration 002)."""
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL app.auth_lookup = '1'"))


def _org_by_customer_id(db: Session, customer_id: str) -> m.Organization | None:
    _bootstrap_org_lookup(db)
    return db.query(m.Organization).filter_by(stripe_customer_id=customer_id).first()


def _org_by_id_str(db: Session, org_id: str) -> m.Organization | None:
    try:
        oid = uuid.UUID(str(org_id))
    except (ValueError, AttributeError, TypeError):
        return None
    _bootstrap_org_lookup(db)
    return db.get(m.Organization, oid)


def _set_org_context(db: Session, org: m.Organization) -> None:
    """Pin RLS to the org and re-load under its policy (defense in depth)."""
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL app.org_id = :org_id"), {"org_id": str(org.id)})
        db.execute(text("SET LOCAL app.auth_lookup = ''"))
        org = db.get(m.Organization, org.id)
    return org


def _as_id(value) -> str | None:
    """Stripe expandables arrive as id strings or objects — normalize."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.get("id")


def _record_event(db: Session, event_id: str, event_type: str,
                  org_id: uuid.UUID | None) -> bool:
    """Persist a processed webhook event id. Returns False if already seen."""
    db.add(m.StripeWebhookEvent(event_id=event_id, event_type=event_type, org_id=org_id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def handle_checkout_completed(db: Session, session_obj: dict) -> str | None:
    meta = session_obj.get("metadata") or {}
    org = _org_by_id_str(db, meta.get("org_id"))
    plan = meta.get("plan")
    if org is None or plan not in PAID_PLANS:
        return None  # unknown org/plan: acknowledge without changes
    org = _set_org_context(db, org)
    org.stripe_customer_id = _as_id(session_obj.get("customer")) or org.stripe_customer_id
    org.stripe_subscription_id = _as_id(session_obj.get("subscription"))
    org.stripe_pending_session_id = None  # checkout finished — clear the reuse slot
    org.plan = plan
    # Session completed in subscription mode with payment taken → active.
    # (We don't use Stripe-side trials.) Later subscription.updated webhooks
    # keep this accurate.
    org.subscription_status = "active"
    org.trial_ends_at = None  # paid plan supersedes any trial
    db.add(org)
    db.flush()
    return str(org.id)


def handle_subscription_updated(db: Session, sub: dict) -> str | None:
    org = _org_by_customer_id(db, _as_id(sub.get("customer")))
    if org is None:
        return None
    org = _set_org_context(db, org)
    org.subscription_status = sub.get("status")
    org.stripe_subscription_id = sub.get("id")
    items = (sub.get("items") or {}).get("data") or []
    price_id = (items[0].get("price") or {}).get("id") if items else None
    plan = plan_for_price_id(price_id)
    if plan:
        org.plan = plan
    # A canceled-then-ended subscription keeps status "canceled"; the
    # deleted webhook handles the final transition.
    db.add(org)
    db.flush()
    return str(org.id)


def handle_subscription_deleted(db: Session, sub: dict) -> str | None:
    org = _org_by_customer_id(db, _as_id(sub.get("customer")))
    if org is None:
        return None
    org = _set_org_context(db, org)
    org.subscription_status = "canceled"
    org.plan = "free"
    org.stripe_pending_session_id = None
    db.add(org)
    db.flush()
    return str(org.id)


def handle_invoice_payment_failed(db: Session, invoice: dict) -> str | None:
    org = _org_by_customer_id(db, _as_id(invoice.get("customer")))
    if org is None:
        return None
    org = _set_org_context(db, org)
    org.subscription_status = "past_due"  # grace: paid access continues
    db.add(org)
    db.flush()
    return str(org.id)


WEBHOOK_HANDLERS = {
    "checkout.session.completed": handle_checkout_completed,
    "customer.subscription.updated": handle_subscription_updated,
    "customer.subscription.deleted": handle_subscription_deleted,
    "invoice.payment_failed": handle_invoice_payment_failed,
}


def verify_webhook_signature(raw_body: bytes, sig_header: str | None) -> "stripe.Event":
    """Verify the Stripe signature; raise HTTPException(400) on any failure.

    Never trust an unverified payload. Missing secret → 503 (fail closed).
    """
    if not stripe_client.webhook_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="webhook secret not configured")
    if not sig_header:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="missing stripe-signature header")
    try:
        return stripe.Webhook.construct_event(
            payload=raw_body,
            sig_header=sig_header,
            secret=settings.stripe_webhook_secret,
        )
    except stripe.SignatureVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"invalid webhook signature: {exc}") from exc
    except Exception as exc:  # malformed payload etc.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"invalid webhook payload: {exc}") from exc


def process_webhook_event(db: Session, event: "stripe.Event") -> dict:
    """Dispatch a verified event. Idempotent on event.id; unknown types/orgs
    are acknowledged with 200 (Stripe retries 4xx/5xx)."""
    # construct_event returns a StripeObject, not a plain dict.
    data = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    event_id = data.get("id")
    event_type = data.get("type")
    obj = (data.get("data") or {}).get("object") or {}

    handler = WEBHOOK_HANDLERS.get(event_type)
    if handler is None:
        _record_event(db, event_id, event_type, None)
        db.commit()
        return {"received": True, "handled": False}

    # Dedupe BEFORE handling so redeliveries can't double-apply.
    if not _record_event(db, event_id, event_type, None):
        db.commit()
        return {"received": True, "handled": False, "duplicate": True}

    org_id = handler(db, obj)
    if org_id:
        # Backfill the org on the recorded event for auditability.
        row = db.query(m.StripeWebhookEvent).filter_by(event_id=event_id).first()
        if row is not None:
            row.org_id = uuid.UUID(org_id)
    db.commit()
    return {"received": True, "handled": True}


def start_trial(org: m.Organization, now: datetime | None = None) -> None:
    """Begin the 14-day cardless trial (called at signup)."""
    org.trial_ends_at = (now or _utcnow()) + timedelta(days=TRIAL_DAYS)
