"""Billing endpoints (JWT auth), except the Stripe webhook.

  GET  /billing/status    current plan, trial, subscription, usage vs limits
  POST /billing/checkout  {plan} -> Stripe Checkout Session URL (idempotent)
  POST /billing/portal    -> Stripe Customer Portal URL
  POST /billing/webhook   Stripe server-to-server events (signature-verified,
                         NO JWT — authenticity is proved by the signature)

Secrets live in env only (STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET) and
never appear in responses or logs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import billing as schemas
from app.services import billing as billing_service
from app.services import stripe_client

router = APIRouter(prefix="/billing", tags=["billing"])


def _org_of(user: m.User, db: Session) -> m.Organization:
    org = db.get(m.Organization, user.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")
    return org


@router.get("/status", response_model=schemas.BillingStatusOut)
def billing_status(user: m.User = Depends(deps.get_current_user),
                   db: Session = Depends(get_db)):
    org = _org_of(user, db)
    st = billing_service.get_billing_status(db, org.id)
    limits = st.limits
    return schemas.BillingStatusOut(
        plan=st.plan,
        effective_plan=st.effective_plan,
        subscription_status=st.subscription_status,
        trial_active=st.trial_active,
        trial_days_left=st.trial_days_left,
        trial_ends_at=st.trial_ends_at,
        has_paid_access=st.has_paid_access,
        stripe_customer_id=st.stripe_customer_id,
        limits=schemas.PlanLimitsOut(
            display_name=limits["display_name"],
            monthly_price_usd=limits["monthly_price_usd"],
            max_projects=limits["max_projects"],
            events_per_month=limits["events_per_month"],
            retention_days=limits["retention_days"],
        ),
        projects_count=st.projects_count,
        events_this_month=st.events_this_month,
        events_over_limit=st.events_over_limit,
        stripe_configured=stripe_client.stripe_configured(),
    )


@router.post("/checkout", response_model=schemas.CheckoutResponse)
def checkout(payload: schemas.CheckoutRequest,
             request: Request,
             user: m.User = Depends(deps.get_current_user),
             db: Session = Depends(get_db)):
    plan = payload.plan.strip().lower()
    if plan not in billing_service.PAID_PLANS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='plan must be one of "starter", "growth"')
    if not stripe_client.stripe_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="billing is not configured")
    org = _org_of(user, db)
    try:
        result = billing_service.create_checkout_session(db, org, plan, user.email)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc
    db.commit()
    return schemas.CheckoutResponse(**result)


@router.post("/portal", response_model=schemas.PortalResponse)
def portal(user: m.User = Depends(deps.get_current_user),
           db: Session = Depends(get_db)):
    if not stripe_client.stripe_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="billing is not configured")
    org = _org_of(user, db)
    try:
        result = billing_service.create_portal_session(db, org)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc
    db.commit()
    return schemas.PortalResponse(**result)


@router.post("/webhook", response_model=schemas.WebhookResponse)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe server-to-server webhook. No JWT: the HMAC signature over the
    RAW body is the authentication. Unsigned/invalid → 400, never processed."""
    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature")
    event = billing_service.verify_webhook_signature(raw_body, sig_header)
    result = billing_service.process_webhook_event(db, event)
    return schemas.WebhookResponse(**result)
