"""Phase 8 tests: Stripe billing.

No live Stripe calls — the SDK client is faked, and webhook signatures are
produced with the real ``stripe.WebhookSignature`` helpers against a
test-only webhook secret. What we verify:
- webhook signature verification (valid / tampered / missing / wrong secret)
- subscription lifecycle via webhooks (checkout → updated → deleted,
  payment_failed) and webhook idempotency (redelivery)
- entitlement gates: trial ok, expired blocked (402), paid ok, canceled blocked
- checkout idempotency (open session reused), 409 when already subscribed
- project caps per plan; cross-org isolation
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import stripe

from app import models as m
from app.api.v1 import deps
from app.services import billing
from app.services import stripe_client

WEBHOOK_SECRET = "whsec_test_only_do_not_use_in_prod"
OTHER_SECRET = "whsec_wrong_secret"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _signup(client, tag="b8"):
    email = f"{tag}-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/api/v1/auth/signup", json={
        "email": email, "password": "correct-horse-9", "org_name": f"{tag} org"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}, \
        body["project"]["id"], body["org"]["id"]


def _pin(db, org_id):
    """Pin the raw test session's RLS context to the org, mirroring the
    authenticated request path. No-op on SQLite."""
    deps.set_rls_org(db, uuid.UUID(str(org_id)))


@pytest.fixture()
def billing_settings(monkeypatch):
    """Test-only billing config (Stripe secrets are never real here)."""
    fake = SimpleNamespace(
        stripe_secret_key="sk_test_fake",
        stripe_webhook_secret=WEBHOOK_SECRET,
        stripe_price_starter="price_starter_test",
        stripe_price_growth="price_growth_test",
        frontend_url="http://localhost:3000",
    )
    monkeypatch.setattr("app.services.billing.settings", fake)
    monkeypatch.setattr("app.services.stripe_client.settings", fake)
    return fake


def _signed_payload(payload: dict, secret: str = WEBHOOK_SECRET,
                    timestamp: int | None = None) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    header = stripe.WebhookSignature.generate_signature_header(
        raw.decode(), secret, timestamp)
    return raw, header


def _event_payload(event_id: str, event_type: str, obj: dict) -> dict:
    return {"id": event_id, "object": "event", "type": event_type,
            "created": 1_700_000_000, "data": {"object": obj},
            "livemode": False, "pending_webhooks": 1,
            "api_version": "2024-01-01", "request": {"id": None, "idempotency_key": None}}


def _post_webhook(client, payload, secret=WEBHOOK_SECRET, headers_extra=None):
    raw, header = _signed_payload(payload, secret)
    headers = {"stripe-signature": header}
    if headers_extra:
        headers.update(headers_extra)
    return client.post("/api/v1/billing/webhook", content=raw, headers=headers)


def _expire_trial(db_url, org_id):
    """Move the org's trial into the past with a real commit.

    NOTE: the ``db`` fixture's session joins an externally-begun transaction,
    so its ``commit()`` is invisible to other connections (and its open txn
    locks SQLite against TestClient writes). Use a dedicated engine here.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {},
    )
    try:
        with SASession(engine) as s:
            # Pin the RLS context exactly as the authenticated app does;
            # without it the org row is invisible under FORCE ROW LEVEL SECURITY.
            deps.set_rls_org(s, uuid.UUID(str(org_id)))
            org = s.get(m.Organization, uuid.UUID(str(org_id)))
            org.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
            s.commit()
    finally:
        engine.dispose()


class _FakeCheckoutSessions:
    def __init__(self, store):
        self._store = store

    def create(self, params=None, options=None):
        self._store["created"] += 1
        sid = f"cs_test_{self._store['created']}"
        self._store["sessions"][sid] = {
            "id": sid, "object": "checkout.session",
            "url": f"https://checkout.stripe.com/pay/{sid}",
            "status": "open", "mode": "subscription",
            "customer": params.get("customer"),
            "subscription": None,
            "metadata": params.get("metadata", {}),
        }
        return self._store["sessions"][sid]

    def retrieve(self, session_id, params=None, options=None):
        if session_id not in self._store["sessions"]:
            raise stripe.NotFoundError("no such session", {})
        return self._store["sessions"][session_id]


class _FakeCustomers:
    def __init__(self, store):
        self._store = store

    def create(self, params=None, options=None):
        self._store["customers_created"] += 1
        cid = f"cus_test_{self._store['customers_created']}"
        self._store["customers"][cid] = {"id": cid, **(params or {})}
        return self._store["customers"][cid]


class _FakePortalSessions:
    def create(self, params=None, options=None):
        return {"id": "bps_test_1", "object": "billing_portal.session",
                "url": "https://billing.stripe.com/session/test",
                "customer": params.get("customer")}


class _FakeV1:
    def __init__(self, store):
        self.checkout = SimpleNamespace(sessions=_FakeCheckoutSessions(store))
        self.customers = _FakeCustomers(store)
        self.billing_portal = SimpleNamespace(sessions=_FakePortalSessions())


class _FakeStripeClient:
    def __init__(self):
        self._store = {"created": 0, "customers_created": 0,
                       "sessions": {}, "customers": {}}
        self.v1 = _FakeV1(self._store)

    @property
    def store(self):
        return self._store


@pytest.fixture()
def fake_stripe(monkeypatch):
    fake = _FakeStripeClient()
    monkeypatch.setattr(stripe_client, "get_stripe_client", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# webhook signature verification
# ---------------------------------------------------------------------------

class TestWebhookSignature:
    def test_valid_signature_accepted(self, client, billing_settings):
        body, _, _, org_id = _signup(client, "sig1")
        payload = _event_payload("evt_sig_ok", "ping", {})
        r = _post_webhook(client, payload)
        assert r.status_code == 200, r.text
        assert r.json()["received"] is True

    def test_missing_signature_rejected(self, client, billing_settings):
        raw = json.dumps(_event_payload("evt_sig_miss", "ping", {})).encode()
        r = client.post("/api/v1/billing/webhook", content=raw)
        assert r.status_code == 400

    def test_tampered_body_rejected(self, client, billing_settings):
        payload = _event_payload("evt_sig_tamper", "ping", {})
        raw, header = _signed_payload(payload)
        tampered = raw.replace(b"ping", b"pong")
        r = client.post("/api/v1/billing/webhook", content=tampered,
                        headers={"stripe-signature": header})
        assert r.status_code == 400

    def test_wrong_secret_rejected(self, client, billing_settings):
        payload = _event_payload("evt_sig_wrong", "ping", {})
        r = _post_webhook(client, payload, secret=OTHER_SECRET)
        assert r.status_code == 400

    def test_unconfigured_secret_fails_closed(self, client, monkeypatch):
        fake = SimpleNamespace(
            stripe_secret_key="sk_test_fake", stripe_webhook_secret="",
            stripe_price_starter="p1", stripe_price_growth="p2",
            frontend_url="http://localhost:3000")
        monkeypatch.setattr("app.services.billing.settings", fake)
        monkeypatch.setattr("app.services.stripe_client.settings", fake)
        payload = _event_payload("evt_sig_nosecret", "ping", {})
        raw, header = _signed_payload(payload)
        r = client.post("/api/v1/billing/webhook", content=raw,
                        headers={"stripe-signature": header})
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# subscription lifecycle via webhooks
# ---------------------------------------------------------------------------

class TestWebhookLifecycle:
    def _checkout_completed(self, org_id, plan="starter", event_id="evt_co_1",
                            customer="cus_test_1", subscription="sub_test_1"):
        return _event_payload(event_id, "checkout.session.completed", {
            "id": "cs_test_1", "object": "checkout.session",
            "customer": customer, "subscription": subscription,
            "metadata": {"org_id": str(org_id), "plan": plan}})

    def test_checkout_completed_activates_plan(self, client, db, billing_settings):
        body, headers, _, org_id = _signup(client, "lc1")
        r = _post_webhook(client, self._checkout_completed(org_id))
        assert r.status_code == 200, r.text
        assert r.json()["handled"] is True
        _pin(db, org_id)
        org = db.get(m.Organization, uuid.UUID(str(org_id)))
        assert org.plan == "starter"
        assert org.subscription_status == "active"
        assert org.stripe_customer_id == "cus_test_1"
        assert org.stripe_subscription_id == "sub_test_1"
        assert org.stripe_pending_session_id is None
        assert org.trial_ends_at is None  # paid supersedes trial

    def test_webhook_redelivery_is_idempotent(self, client, db, billing_settings):
        _, _, _, org_id = _signup(client, "lc2")
        payload = self._checkout_completed(org_id, event_id="evt_co_dup")
        r1 = _post_webhook(client, payload)
        r2 = _post_webhook(client, payload)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r2.json().get("duplicate") is True
        n = db.query(m.StripeWebhookEvent).filter_by(event_id="evt_co_dup").count()
        assert n == 1

    def test_subscription_updated_maps_price_to_plan(self, client, db, billing_settings):
        _, _, _, org_id = _signup(client, "lc3")
        _post_webhook(client, self._checkout_completed(org_id, event_id="evt_lc3a", customer="cus_lc3", subscription="sub_lc3"))
        payload = _event_payload("evt_lc3b", "customer.subscription.updated", {
            "id": "sub_lc3", "object": "subscription",
            "customer": "cus_lc3", "status": "active",
            "items": {"data": [{"price": {"id": "price_growth_test"}}]}})
        r = _post_webhook(client, payload)
        assert r.status_code == 200, r.text
        _pin(db, org_id)
        org = db.get(m.Organization, uuid.UUID(str(org_id)))
        assert org.plan == "growth"  # upgraded via portal

    def test_subscription_updated_unknown_price_keeps_plan(self, client, db, billing_settings):
        _, _, _, org_id = _signup(client, "lc4")
        _post_webhook(client, self._checkout_completed(org_id, event_id="evt_lc4a", customer="cus_lc4", subscription="sub_lc4"))
        payload = _event_payload("evt_lc4b", "customer.subscription.updated", {
            "id": "sub_lc4", "object": "subscription",
            "customer": "cus_lc4", "status": "active",
            "items": {"data": [{"price": {"id": "price_unknown_xyz"}}]}})
        r = _post_webhook(client, payload)
        assert r.status_code == 200, r.text
        _pin(db, org_id)
        org = db.get(m.Organization, uuid.UUID(str(org_id)))
        assert org.plan == "starter"  # unchanged
        assert org.subscription_status == "active"

    def test_subscription_deleted_cancels(self, client, db, billing_settings):
        _, _, _, org_id = _signup(client, "lc5")
        _post_webhook(client, self._checkout_completed(org_id, event_id="evt_lc5a", customer="cus_lc5", subscription="sub_lc5"))
        payload = _event_payload("evt_lc5b", "customer.subscription.deleted", {
            "id": "sub_lc5", "object": "subscription", "customer": "cus_lc5"})
        r = _post_webhook(client, payload)
        assert r.status_code == 200, r.text
        _pin(db, org_id)
        org = db.get(m.Organization, uuid.UUID(str(org_id)))
        assert org.subscription_status == "canceled"
        assert org.plan == "free"

    def test_invoice_payment_failed_marks_past_due(self, client, db, billing_settings):
        _, _, _, org_id = _signup(client, "lc6")
        _post_webhook(client, self._checkout_completed(org_id, event_id="evt_lc6a", customer="cus_lc6", subscription="sub_lc6"))
        payload = _event_payload("evt_lc6b", "invoice.payment_failed", {
            "id": "in_test_1", "object": "invoice", "customer": "cus_lc6",
            "subscription": "sub_lc6"})
        r = _post_webhook(client, payload)
        assert r.status_code == 200, r.text
        _pin(db, org_id)
        org = db.get(m.Organization, uuid.UUID(str(org_id)))
        assert org.subscription_status == "past_due"
        # past_due keeps paid access (grace)
        assert billing.has_paid_access(org) is True

    def test_unknown_customer_acknowledged_not_applied(self, client, db, billing_settings):
        _, _, _, org_id = _signup(client, "lc7")
        payload = _event_payload("evt_lc7", "customer.subscription.deleted", {
            "id": "sub_nope", "object": "subscription", "customer": "cus_nope"})
        r = _post_webhook(client, payload)
        assert r.status_code == 200  # Stripe retries 4xx/5xx; acknowledge instead
        _pin(db, org_id)
        org = db.get(m.Organization, uuid.UUID(str(org_id)))
        assert org.plan == "free" and org.subscription_status is None

    def test_unknown_event_type_acknowledged(self, client, billing_settings):
        _signup(client, "lc8")
        payload = _event_payload("evt_lc8", "customer.created", {"id": "cus_x"})
        r = _post_webhook(client, payload)
        assert r.status_code == 200
        assert r.json()["handled"] is False


# ---------------------------------------------------------------------------
# entitlements
# ---------------------------------------------------------------------------

class TestEntitlements:
    def test_fresh_signup_gets_trial(self, client):
        body, headers, _, _ = _signup(client, "en1")
        r = client.get("/api/v1/billing/status", headers=headers)
        assert r.status_code == 200, r.text
        st = r.json()
        assert st["trial_active"] is True
        assert st["has_paid_access"] is True
        assert st["effective_plan"] == "growth"  # trial = full features
        assert st["trial_days_left"] is not None and 0 < st["trial_days_left"] <= 14

    def test_trial_org_passes_paid_gates(self, client):
        _, headers, project_id, _ = _signup(client, "en2")
        # anomaly feed is a paid feature; trial passes the gate (empty feed ok)
        r = client.get(f"/api/v1/projects/{project_id}/anomalies", headers=headers)
        assert r.status_code == 200, r.text
        # provider sync gate passes too (fails later on unknown credential)
        r = client.post("/api/v1/integrations/providers/nope/sync?project_id=" + project_id,
                        json={"days_back": 7}, headers=headers)
        assert r.status_code == 404, r.text  # past the 402 gate, cred not found

    def test_expired_trial_blocked_from_paid_features(self, client, db_url):
        _, headers, project_id, org_id = _signup(client, "en3")
        _expire_trial(db_url, org_id)
        r = client.get("/api/v1/billing/status", headers=headers)
        assert r.json()["has_paid_access"] is False
        assert r.json()["effective_plan"] == "free"
        r = client.get(f"/api/v1/projects/{project_id}/anomalies", headers=headers)
        assert r.status_code == 402, r.text
        r = client.post("/api/v1/integrations/providers/nope/sync?project_id=" + project_id,
                        json={"days_back": 7}, headers=headers)
        assert r.status_code == 402, r.text
        # acknowledge carries the anomaly's dollar figures, so it is gated too
        r = client.post(
            f"/api/v1/projects/{project_id}/anomalies/00000000-0000-0000-0000-000000000000/acknowledge",
            headers=headers)
        assert r.status_code == 402, r.text

    def test_expired_trial_keeps_free_features(self, client, db_url):
        _, headers, project_id, org_id = _signup(client, "en4")
        _expire_trial(db_url, org_id)
        # dashboard, P&L, investigate stay available on the free tier
        assert client.get(f"/api/v1/projects/{project_id}/dashboard",
                          headers=headers).status_code == 200
        assert client.get(f"/api/v1/projects/{project_id}/pnl",
                          headers=headers).status_code == 200

    def test_paid_org_passes_gates(self, client, db, billing_settings):
        _, headers, project_id, org_id = _signup(client, "en5")
        payload = _event_payload("evt_en5", "checkout.session.completed", {
            "id": "cs_en5", "object": "checkout.session",
            "customer": "cus_en5", "subscription": "sub_en5",
            "metadata": {"org_id": str(org_id), "plan": "starter"}})
        _post_webhook(client, payload)
        st = client.get("/api/v1/billing/status", headers=headers).json()
        assert st["has_paid_access"] is True and st["effective_plan"] == "starter"
        assert client.get(f"/api/v1/projects/{project_id}/anomalies",
                          headers=headers).status_code == 200

    def test_canceled_subscription_loses_paid_access(self, client, db, billing_settings):
        _, headers, project_id, org_id = _signup(client, "en6")
        _post_webhook(client, _event_payload("evt_en6a", "checkout.session.completed", {
            "id": "cs_en6", "object": "checkout.session",
            "customer": "cus_en6", "subscription": "sub_en6",
            "metadata": {"org_id": str(org_id), "plan": "starter"}}))
        _post_webhook(client, _event_payload("evt_en6b", "customer.subscription.deleted", {
            "id": "sub_en6", "object": "subscription", "customer": "cus_en6"}))
        assert client.get(f"/api/v1/projects/{project_id}/anomalies",
                          headers=headers).status_code == 402

    def test_project_caps(self, client, db_url):
        # free (expired trial): 1 project max — the default project fills it
        _, headers, _, org_id = _signup(client, "en7")
        _expire_trial(db_url, org_id)
        r = client.post("/api/v1/projects", json={"name": "Second"}, headers=headers)
        assert r.status_code == 402, r.text

    def test_trial_allows_second_project(self, client):
        _, headers, _, _ = _signup(client, "en8")
        r = client.post("/api/v1/projects", json={"name": "Second"}, headers=headers)
        assert r.status_code == 201, r.text
        assert r.json()["name"] == "Second"

    def test_growth_allows_five_projects(self, client, db, billing_settings):
        _, headers, _, org_id = _signup(client, "en9")
        _post_webhook(client, _event_payload("evt_en9", "checkout.session.completed", {
            "id": "cs_en9", "object": "checkout.session",
            "customer": "cus_en9", "subscription": "sub_en9",
            "metadata": {"org_id": str(org_id), "plan": "growth"}}))
        for i in range(4):  # default + 4 = 5
            r = client.post("/api/v1/projects", json={"name": f"P{i}"}, headers=headers)
            assert r.status_code == 201, r.text
        r = client.post("/api/v1/projects", json={"name": "Sixth"}, headers=headers)
        assert r.status_code == 402, r.text


# ---------------------------------------------------------------------------
# checkout / portal
# ---------------------------------------------------------------------------

class TestCheckoutPortal:
    def test_checkout_creates_session(self, client, billing_settings, fake_stripe):
        _, headers, _, org_id = _signup(client, "co1")
        r = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                        headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["url"].startswith("https://checkout.stripe.com/pay/")
        assert body["reused"] is False
        assert fake_stripe.store["created"] == 1
        assert fake_stripe.store["customers_created"] == 1  # customer created once

    def test_checkout_reuses_open_session(self, client, billing_settings, fake_stripe):
        _, headers, _, _ = _signup(client, "co2")
        r1 = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                         headers=headers).json()
        r2 = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                         headers=headers).json()
        assert r2["reused"] is True
        assert r2["url"] == r1["url"]
        assert fake_stripe.store["created"] == 1  # no second Stripe session

    def test_checkout_does_not_reuse_session_for_different_plan(
        self, client, billing_settings, fake_stripe
    ):
        _, headers, _, _ = _signup(client, "co2b")
        r1 = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                         headers=headers).json()
        r2 = client.post("/api/v1/billing/checkout", json={"plan": "growth"},
                         headers=headers).json()
        assert r2["reused"] is False
        assert r2["url"] != r1["url"]  # new session for the new plan/price
        assert fake_stripe.store["created"] == 2

    def test_checkout_recreates_after_completion(self, client, billing_settings, fake_stripe):
        _, headers, _, _ = _signup(client, "co3")
        r1 = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                         headers=headers).json()
        # simulate the first session completing at Stripe
        fake_stripe.store["sessions"][r1["session_id"]]["status"] = "complete"
        r2 = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                         headers=headers).json()
        assert r2["reused"] is False and r2["url"] != r1["url"]
        assert fake_stripe.store["created"] == 2

    def test_checkout_rejects_bad_plan(self, client, billing_settings, fake_stripe):
        _, headers, _, _ = _signup(client, "co4")
        r = client.post("/api/v1/billing/checkout", json={"plan": "enterprise"},
                        headers=headers)
        assert r.status_code == 400

    def test_checkout_conflicts_when_already_subscribed(self, client, billing_settings, fake_stripe):
        _, headers, _, org_id = _signup(client, "co5")
        _post_webhook(client, _event_payload("evt_co5", "checkout.session.completed", {
            "id": "cs_co5", "object": "checkout.session",
            "customer": "cus_co5", "subscription": "sub_co5",
            "metadata": {"org_id": str(org_id), "plan": "starter"}}))
        r = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                        headers=headers)
        assert r.status_code == 409, r.text

    def test_checkout_unconfigured_stripe_503(self, client, monkeypatch):
        fake = SimpleNamespace(
            stripe_secret_key="", stripe_webhook_secret=WEBHOOK_SECRET,
            stripe_price_starter="p1", stripe_price_growth="p2",
            frontend_url="http://localhost:3000")
        monkeypatch.setattr("app.services.billing.settings", fake)
        monkeypatch.setattr("app.services.stripe_client.settings", fake)
        _, headers, _, _ = _signup(client, "co6")
        r = client.post("/api/v1/billing/checkout", json={"plan": "starter"},
                        headers=headers)
        assert r.status_code == 503

    def test_portal_returns_url(self, client, billing_settings, fake_stripe):
        _, headers, _, org_id = _signup(client, "po1")
        _post_webhook(client, _event_payload("evt_po1", "checkout.session.completed", {
            "id": "cs_po1", "object": "checkout.session",
            "customer": "cus_po1", "subscription": "sub_po1",
            "metadata": {"org_id": str(org_id), "plan": "starter"}}))
        r = client.post("/api/v1/billing/portal", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["url"].startswith("https://billing.stripe.com/")

    def test_portal_without_customer_404(self, client, billing_settings, fake_stripe):
        _, headers, _, _ = _signup(client, "po2")
        r = client.post("/api/v1/billing/portal", headers=headers)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# service-level unit checks + isolation
# ---------------------------------------------------------------------------

class TestBillingService:
    def test_require_paid_feature_unknown_feature(self, client, db):
        body, _, _, _ = _signup(client, "sv1")
        user = db.get(m.User, uuid.UUID(body["user"]["id"]))
        with pytest.raises(ValueError):
            billing.require_paid_feature(user, db, "nope")

    def test_status_response_contract(self, client):
        # Locks the /billing/status shape the frontend (/app/billing) renders.
        _, headers, _, _ = _signup(client, "sv4")
        st = client.get("/api/v1/billing/status", headers=headers).json()
        assert set(st.keys()) == {
            "plan", "effective_plan", "subscription_status", "trial_active",
            "trial_days_left", "trial_ends_at", "has_paid_access",
            "stripe_customer_id", "limits", "projects_count",
            "events_this_month", "events_over_limit", "stripe_configured",
            "data_label",
        }
        assert set(st["limits"].keys()) == {
            "display_name", "monthly_price_usd", "max_projects",
            "events_per_month", "retention_days",
        }

    def test_status_never_exposes_secrets(self, client):
        _, headers, _, _ = _signup(client, "sv2")
        st = client.get("/api/v1/billing/status", headers=headers).json()
        blob = json.dumps(st).lower()
        assert "sk_test" not in blob and "sk_live" not in blob
        assert "whsec" not in blob

    def test_webhook_for_org_a_does_not_touch_org_b(self, client, billing_settings):
        _, _, _, org_a = _signup(client, "iso1")
        _, headers_b, _, org_b = _signup(client, "iso2")
        _post_webhook(client, _event_payload("evt_iso", "checkout.session.completed", {
            "id": "cs_iso", "object": "checkout.session",
            "customer": "cus_iso", "subscription": "sub_iso",
            "metadata": {"org_id": str(org_a), "plan": "growth"}}))
        st_b = client.get("/api/v1/billing/status", headers=headers_b).json()
        assert st_b["plan"] == "free" and st_b["subscription_status"] is None
        assert st_b["has_paid_access"] is True  # org B still on its own trial

    def test_monthly_event_count(self, client, db):
        _, _, project_id, org_id = _signup(client, "sv3")
        _pin(db, org_id)
        now = datetime.now(timezone.utc)
        for i in range(3):
            db.add(m.UsageEvent(
                org_id=uuid.UUID(str(org_id)), project_id=uuid.UUID(str(project_id)),
                source="event_api", provider="openai", model="gpt-4o-mini",
                occurred_at=now - timedelta(days=i),
                input_tokens=100, output_tokens=50))
        db.commit()
        assert billing.monthly_event_count(db, uuid.UUID(str(org_id))) == 3
