"""Phase 4 tests: OpenAI + Anthropic connectors.

All provider HTTP is mocked via httpx.MockTransport — no real network, no
real keys. What we verify:
- usage buckets → usage_events with deterministic calculated costs
- cost reports stored separately (never allocated to models)
- unpriced models stored NULL + surfaced in the sync summary
- invalid/non-admin keys rejected at connect time; nothing stored
- key material never persisted in plaintext
- sync is idempotent (re-run → no duplicates)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app import models as m
from app.api.v1 import deps
from app.services import costing
from app.services.providers import anthropic as anthropic_mod
from app.services.providers import openai as openai_mod
from app.services.providers.base import ProviderError
from app.services.providers.sync import sync_provider
from app.services.secrets import decrypt_secret, encrypt_secret


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _signup(client, tag="p4"):
    email = f"{tag}-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/api/v1/auth/signup", json={
        "email": email, "password": "correct-horse-9", "org_name": f"{tag} org"})
    assert r.status_code == 201, r.text
    body = r.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return body, headers, body["project"]["id"], body["org"]["id"]


def _make_cred(db, org_id, provider, key="sk-test-key-1234567890"):
    cred = m.ProviderCredential(
        org_id=uuid.UUID(str(org_id)), provider=provider, label="test",
        encrypted_key=encrypt_secret(key, org_id=str(org_id)),
        key_last4=key[-4:], status="active")
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


def _rls(db, org_id):
    deps.set_rls_org(db, uuid.UUID(str(org_id)))


def _make_org_project(db, tag):
    """Create an org + project (same order as signup: org under the pre-auth
    RLS bootstrap, then the project once the org context is pinned)."""
    with deps.pre_auth_lookup(db):
        org = m.Organization(name=f"p4-{tag}", slug=f"p4-{tag}-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()
    _rls(db, org.id)
    proj = m.Project(org_id=org.id, name="p")
    db.add(proj)
    db.flush()
    return org, proj


@pytest.fixture(scope="module", autouse=True)
def catalog_seeded(db_url):
    from sqlalchemy import create_engine
    engine = create_engine(db_url)
    with engine.begin() as conn:
        from sqlalchemy.orm import sessionmaker
        s = sessionmaker(bind=conn)()
        costing.ensure_catalog_in_db(s)
        s.commit()
        s.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# mock transports
# ---------------------------------------------------------------------------

def _recent_day_starts():
    """Two recent UTC day-boundary timestamps so buckets fall inside the
    sync window (mocks must not use fixed 2025 dates)."""
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    day2 = int((today - timedelta(days=2)).timestamp())
    day1 = int((today - timedelta(days=1)).timestamp())
    return day2, day1, today


def _openai_transport():
    day2, day1, today = _recent_day_starts()

    # Two daily buckets, grouped by model: gpt-4.1 (priced) + gpt-zzz (unpriced)
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/organization/costs":
            params = dict(request.url.params)
            if params.get("limit") == "1" and "group_by" not in params:
                return httpx.Response(200, json={"data": [], "has_more": False})
            return httpx.Response(200, json={
                "data": [{
                    "object": "bucket", "start_time": day2, "end_time": day1,
                    "results": [
                        {"object": "organization.costs.result",
                         "amount": {"currency": "usd", "value": 12.5},
                         "line_item": "text tokens"},
                    ]}],
                "has_more": False})
        if path == "/v1/organization/usage/completions":
            return httpx.Response(200, json={
                "data": [
                    {"object": "bucket", "start_time": day2, "end_time": day1,
                     "results": [
                         {"object": "organization.usage.completions.result",
                          "input_tokens": 1_000_000, "output_tokens": 500_000,
                          "input_cached_tokens": 200_000, "num_model_requests": 42,
                          "model": "gpt-4.1", "api_key_id": "key_1",
                          "project_id": None, "user_id": None, "batch": None},
                         {"object": "organization.usage.completions.result",
                          "input_tokens": 10_000, "output_tokens": 5_000,
                          "input_cached_tokens": 0, "num_model_requests": 3,
                          "model": "gpt-zzz-unpriced", "api_key_id": None,
                          "project_id": None, "user_id": None, "batch": None},
                     ]},
                    {"object": "bucket", "start_time": day1,
                     "end_time": int(today.timestamp()), "results": []},
                ],
                "has_more": False})
        return httpx.Response(404, json={"error": {"message": "not found"}})
    return httpx.MockTransport(handler)


def _anthropic_transport():
    day2, day1, _today = _recent_day_starts()
    start = datetime.fromtimestamp(day2, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = datetime.fromtimestamp(day1, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/organizations/usage_report/messages":
            params = dict(request.url.params)
            if params.get("limit") == "1":
                return httpx.Response(200, json={"data": [], "has_more": False})
            return httpx.Response(200, json={
                "data": [{
                    "starting_at": start,
                    "ending_at": end,
                    "results": [{
                        "model": "claude-3-5-haiku-20241022",
                        "input_tokens": 2_000_000,
                        "output_tokens": 500_000,
                        "cache_read_input_tokens": 1_000_000,
                        "cache_creation_input_tokens": 250_000,
                        "workspace_id": "ws_1",
                    }],
                }],
                "has_more": False, "next_page": None})
        if path == "/v1/organizations/cost_report":
            return httpx.Response(200, json={
                "data": [{
                    "starting_at": start,
                    "ending_at": end,
                    "results": [{
                        "description": "Inference",
                        "workspace_id": "ws_1",
                        "amount": "4250",  # cents → $42.50
                    }],
                }],
                "has_more": False, "next_page": None})
        return httpx.Response(404, json={"type": "not_found_error"})
    return httpx.MockTransport(handler)


def _error_transport(status: int, body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# unit: parsing + error mapping
# ---------------------------------------------------------------------------

def test_openai_parse_usage_splits_cached_tokens():
    parsed = openai_mod.parse_usage_result({
        "model": "gpt-4.1", "input_tokens": 1_000_000,
        "output_tokens": 500_000, "input_cached_tokens": 200_000,
        "num_model_requests": 42, "api_key_id": "key_1"})
    assert parsed["input_tokens"] == 800_000
    assert parsed["cached_input_tokens"] == 200_000
    assert parsed["output_tokens"] == 500_000
    assert parsed["api_key_id"] == "key_1"


def test_openai_parse_usage_skips_null_model():
    assert openai_mod.parse_usage_result({"model": None, "input_tokens": 5}) is None


def test_openai_401_maps_to_invalid_key():
    client = openai_mod.OpenAIClient(
        "bad", transport=_error_transport(401, {"error": {"message": "bad key"}}))
    with pytest.raises(ProviderError) as ei:
        client.validate()
    assert ei.value.kind == "invalid_key"
    # safe to surface: provider's message, never key material
    assert "sk-bad" not in ei.value.detail and "bad" in ei.value.detail
    client.close()


def test_openai_403_explains_admin_key_requirement():
    client = openai_mod.OpenAIClient(
        "sk-proj", transport=_error_transport(403, {"error": {"message": "denied"}}))
    with pytest.raises(ProviderError) as ei:
        client.validate()
    assert ei.value.kind == "forbidden"
    assert "Admin API key" in ei.value.detail
    client.close()


def test_anthropic_parse_usage_and_cost():
    parsed = anthropic_mod.parse_usage_result({
        "model": "claude-3-5-haiku-20241022", "input_tokens": 2_000_000,
        "output_tokens": 500_000, "cache_read_input_tokens": 1_000_000,
        "cache_creation_input_tokens": 250_000, "workspace_id": "ws_1"})
    assert parsed["input_tokens"] == 2_000_000
    assert parsed["cached_input_tokens"] == 1_000_000
    assert parsed["cache_creation_input_tokens"] == 250_000
    assert parsed["workspace_id"] == "ws_1"

    cost = anthropic_mod.parse_cost_result(
        {"description": "Inference", "amount": "4250"})
    assert cost["amount_usd"] == pytest.approx(42.50)
    assert cost["group_key"] == "Inference"


# ---------------------------------------------------------------------------
# sync: OpenAI
# ---------------------------------------------------------------------------

def test_openai_sync_writes_events_with_calculated_costs(db):
    org, proj = _make_org_project(db, "oai")
    cred = _make_cred(db, org.id, "openai")

    summary = sync_provider(db, org_id=org.id, project_id=proj.id,
                            credential=cred, days_back=7,
                            transport=_openai_transport())
    assert summary.provider == "openai"
    assert summary.events_written == 2
    assert summary.cost_reports_written == 1
    assert summary.unpriced_models == ["gpt-zzz-unpriced"]

    events = (db.query(m.UsageEvent)
              .filter_by(org_id=org.id, project_id=proj.id, source="openai")
              .order_by(m.UsageEvent.model).all())
    assert len(events) == 2

    priced = next(e for e in events if e.model == "gpt-4.1")
    # 800k uncached @ $2/1M + 500k out @ $8/1M + 200k cached @ $0.50/1M
    expected = (Decimal(800_000) * Decimal("2.00")
                + Decimal(500_000) * Decimal("8.00")
                + Decimal(200_000) * Decimal("0.50")) / Decimal(1_000_000)
    assert priced.cost_calculated_usd == expected
    assert priced.cost_reported_usd is None  # provider gives no per-model dollars
    assert priced.application is None and priced.tenant_id is None
    assert priced.meta["api_key_id"] == "key_1"
    assert priced.meta["num_model_requests"] == 42

    unpriced = next(e for e in events if e.model == "gpt-zzz-unpriced")
    assert unpriced.cost_calculated_usd is None  # missing data, not invented

    # cost reports are separate rows — never allocated to models
    reports = db.query(m.ProviderCostReport).filter_by(
        org_id=org.id, project_id=proj.id, provider="openai").all()
    assert len(reports) == 1
    assert reports[0].amount_usd == Decimal("12.5")
    assert reports[0].group_key == "text tokens"

    assert cred.status == "active" and cred.last_sync_at is not None


def test_openai_sync_is_idempotent(db):
    org, proj = _make_org_project(db, "idem")
    cred = _make_cred(db, org.id, "openai")
    kw = dict(db=db, org_id=org.id, project_id=proj.id, credential=cred,
              days_back=7, transport=_openai_transport())
    s1 = sync_provider(**kw)
    s2 = sync_provider(**kw)
    assert s1.events_written == s2.events_written == 2
    count = db.query(m.UsageEvent).filter_by(
        org_id=org.id, project_id=proj.id, source="openai").count()
    assert count == 2
    rcount = db.query(m.ProviderCostReport).filter_by(
        org_id=org.id, project_id=proj.id, provider="openai").count()
    assert rcount == 1


def test_sync_marks_credential_error_on_provider_failure(db):
    org, proj = _make_org_project(db, "err")
    cred = _make_cred(db, org.id, "openai")
    with pytest.raises(ProviderError):
        sync_provider(db, org_id=org.id, project_id=proj.id, credential=cred,
                      days_back=7,
                      transport=_error_transport(500, {"error": {"message": "boom"}}))
    assert cred.status == "error"


# ---------------------------------------------------------------------------
# sync: Anthropic
# ---------------------------------------------------------------------------

def test_anthropic_sync_writes_events_and_cost_reports(db):
    org, proj = _make_org_project(db, "anth")
    cred = _make_cred(db, org.id, "anthropic")

    summary = sync_provider(db, org_id=org.id, project_id=proj.id,
                            credential=cred, days_back=7,
                            transport=_anthropic_transport())
    assert summary.events_written == 1
    assert summary.cost_reports_written == 1
    assert summary.unpriced_models == []

    ev = db.query(m.UsageEvent).filter_by(
        org_id=org.id, project_id=proj.id, source="anthropic").one()
    # 2M in @ $0.80/1M + 500k out @ $4/1M + 1M cached @ $0.08/1M
    expected = (Decimal(2_000_000) * Decimal("0.80")
                + Decimal(500_000) * Decimal("4.00")
                + Decimal(1_000_000) * Decimal("0.08")) / Decimal(1_000_000)
    assert ev.cost_calculated_usd == expected
    assert ev.cost_reported_usd is None
    # cache creation is surfaced, not priced, not folded elsewhere
    assert ev.meta["cache_creation_input_tokens"] == 250_000
    assert ev.meta["workspace_id"] == "ws_1"

    rep = db.query(m.ProviderCostReport).filter_by(
        org_id=org.id, project_id=proj.id, provider="anthropic").one()
    assert rep.amount_usd == Decimal("42.50")  # 4250 cents
    assert rep.group_key == "Inference"


# ---------------------------------------------------------------------------
# API: connect / list / sync / disconnect
# ---------------------------------------------------------------------------

def test_connect_rejects_invalid_key_and_stores_nothing(client, db, monkeypatch):
    body, headers, project_id, org_id = _signup(client, "p4conn")

    from app.api.v1.endpoints import providers as providers_ep

    def fake_client_for(provider, api_key, transport=None):
        class FakeClient:
            def validate(self):
                raise ProviderError(provider, "invalid API key (bad key)",
                                    status_code=401, kind="invalid_key")
            def close(self):
                pass
        return FakeClient()
    monkeypatch.setattr(providers_ep, "_client_for", fake_client_for)

    r = client.post("/api/v1/integrations/providers",
                    json={"provider": "openai", "api_key": "sk-bad-key-123"},
                    headers=headers)
    assert r.status_code == 422, r.text
    assert "invalid API key" in r.json()["detail"]

    _rls(db, org_id)
    assert db.query(m.ProviderCredential).filter_by(
        org_id=uuid.UUID(org_id)).count() == 0


def test_connect_stores_encrypted_key_and_lists_without_material(client, db, monkeypatch):
    body, headers, project_id, org_id = _signup(client, "p4conn2")

    from app.api.v1.endpoints import providers as providers_ep

    def fake_client_for(provider, api_key, transport=None):
        assert api_key == "sk-admin-good-key-12345"
        class FakeClient:
            def validate(self):
                return None
            def close(self):
                pass
        return FakeClient()
    monkeypatch.setattr(providers_ep, "_client_for", fake_client_for)

    r = client.post("/api/v1/integrations/providers",
                    json={"provider": "anthropic", "api_key": "sk-admin-good-key-12345",
                          "label": "prod"},
                    headers=headers)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["provider"] == "anthropic"
    assert info["key_last4"] == "2345"
    assert info["status"] == "active"

    _rls(db, org_id)
    cred = db.query(m.ProviderCredential).filter_by(
        org_id=uuid.UUID(org_id)).one()
    assert cred.encrypted_key != b"sk-admin-good-key-12345"
    assert b"sk-admin-good-key" not in bytes(cred.encrypted_key)
    assert decrypt_secret(cred.encrypted_key, org_id=org_id) == "sk-admin-good-key-12345"

    r = client.get("/api/v1/integrations/providers", headers=headers)
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    assert "api_key" not in json.dumps(listed)
    assert "encrypted" not in json.dumps(listed).lower()

    r = client.delete(f"/api/v1/integrations/providers/{info['id']}", headers=headers)
    assert r.status_code == 204
    r = client.get("/api/v1/integrations/providers", headers=headers)
    assert r.json() == []


def test_sync_endpoint_runs_provider_sync(client, db, monkeypatch):
    body, headers, project_id, org_id = _signup(client, "p4sync")

    from app.api.v1.endpoints import providers as providers_ep
    from app.services.providers import sync as sync_mod

    real_sync = sync_mod.sync_provider

    def fake_sync(db_, *, org_id, project_id, credential, days_back=30,
                  extra_group_by=(), transport=None):
        return real_sync(db_, org_id=org_id, project_id=project_id,
                         credential=credential, days_back=days_back,
                         extra_group_by=extra_group_by,
                         transport=_openai_transport())
    monkeypatch.setattr(providers_ep, "sync_provider", fake_sync)

    def fake_client_for(provider, api_key, transport=None):
        class FakeClient:
            def validate(self):
                return None
            def close(self):
                pass
        return FakeClient()
    monkeypatch.setattr(providers_ep, "_client_for", fake_client_for)

    r = client.post("/api/v1/integrations/providers",
                    json={"provider": "openai", "api_key": "sk-admin-key-xyz123"},
                    headers=headers)
    assert r.status_code == 201, r.text
    cred_id = r.json()["id"]

    r = client.post(f"/api/v1/integrations/providers/{cred_id}/sync",
                    params={"project_id": project_id},
                    json={"days_back": 7}, headers=headers)
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["events_written"] == 2
    assert summary["unpriced_models"] == ["gpt-zzz-unpriced"]

    _rls(db, org_id)
    count = db.query(m.UsageEvent).filter_by(
        org_id=uuid.UUID(org_id), source="openai").count()
    assert count == 2

    r = client.get(f"/api/v1/integrations/providers/{cred_id}/sync-status",
                   headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    assert r.json()["last_sync_at"] is not None


def test_sync_rejects_bad_group_by_and_bad_window(db):
    org, proj = _make_org_project(db, "val")
    cred = _make_cred(db, org.id, "openai")
    with pytest.raises(ProviderError):
        sync_provider(db, org_id=org.id, project_id=proj.id, credential=cred,
                      days_back=7, extra_group_by=("tenant_id",),
                      transport=_openai_transport())
    with pytest.raises(ProviderError):
        sync_provider(db, org_id=org.id, project_id=proj.id, credential=cred,
                      days_back=365, transport=_openai_transport())
