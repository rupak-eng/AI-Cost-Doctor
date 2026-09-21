"""Phase 5 tests: cost-engine hardening (price-version boundaries, single
pricing code path), dashboard aggregations, and tenant P&L status rules —
all against the local test DB (Postgres when available, SQLite fallback).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as m
from app.api.v1 import deps
from app.services import dashboard as dashboard_service
from app.services import pnl as pnl_service
from app.services import recommend
from app.services.costing import (
    Price,
    PriceNotFoundError,
    event_cost,
    load_catalog,
    price_event,
    price_for,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _price(provider: str, model: str, effective_from: date,
           effective_to: date | None = None,
           input_rate: str = "2.00", output_rate: str = "8.00") -> Price:
    return Price(
        provider=provider, model=model,
        input_usd_per_1m=Decimal(input_rate),
        output_usd_per_1m=Decimal(output_rate),
        cached_input_usd_per_1m=None, reasoning_usd_per_1m=None,
        effective_from=effective_from, effective_to=effective_to,
    )


class TestPriceVersionBoundaries:
    def test_boundary_rule_effective_from_inclusive_effective_to_exclusive(self):
        old = _price("openai", "m", date(2026, 1, 1), date(2026, 6, 1),
                     input_rate="2.00", output_rate="8.00")
        new = _price("openai", "m", date(2026, 6, 1), None,
                     input_rate="1.00", output_rate="4.00")
        catalog = [old, new]
        # The day before the change prices at the old rate.
        assert price_for(catalog, provider="openai", model="m",
                         at=date(2026, 5, 31)) is old
        # The change day itself prices at the new rate (effective_to exclusive).
        assert price_for(catalog, provider="openai", model="m",
                         at=date(2026, 6, 1)) is new
        assert price_for(catalog, provider="openai", model="m",
                         at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)) is new

    def test_event_cost_uses_price_effective_at_event_time(self):
        catalog = [
            _price("openai", "m", date(2026, 1, 1), date(2026, 6, 1),
                   input_rate="2.00", output_rate="8.00"),
            _price("openai", "m", date(2026, 6, 1), None,
                   input_rate="1.00", output_rate="4.00"),
        ]
        before = price_event(catalog, provider="openai", model="m",
                             at=datetime(2026, 5, 31, tzinfo=timezone.utc),
                             input_tokens=1_000_000, output_tokens=0)
        after = price_event(catalog, provider="openai", model="m",
                            at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                            input_tokens=1_000_000, output_tokens=0)
        assert before == Decimal("2.00")
        assert after == Decimal("1.00")

    def test_overlapping_rows_latest_effective_from_wins(self):
        a = _price("openai", "m", date(2026, 1, 1), None,
                   input_rate="2.00", output_rate="8.00")
        b = _price("openai", "m", date(2026, 3, 1), None,
                   input_rate="1.50", output_rate="6.00")
        assert price_for([a, b], provider="openai", model="m",
                         at=date(2026, 4, 1)) is b

    def test_no_price_returns_none_never_invented(self):
        catalog = [_price("openai", "m", date(2026, 1, 1), None)]
        assert price_event(catalog, provider="openai", model="m",
                           at=date(2025, 12, 31),
                           input_tokens=100, output_tokens=100) is None
        with pytest.raises(PriceNotFoundError):
            price_for(catalog, provider="openai", model="m", at=date(2025, 12, 31))

    def test_catalog_json_has_no_overlapping_current_prices(self):
        """Sanity: the shipped catalog has at most one current row per model."""
        catalog = load_catalog()
        today = date.today()
        seen = set()
        for p in catalog:
            if p.covers(today):
                key = (p.provider, p.model)
                assert key not in seen, f"duplicate current price for {key}"
                seen.add(key)


class TestSinglePricingPath:
    def test_recommend_pair_cost_matches_engine_event_cost(self):
        price = _price("openai", "m", date(2026, 1, 1), None,
                       input_rate="2.50", output_rate="10.00")
        pair = recommend.PairStats(
            application="chat", provider="openai", model="m",
            requests=100, input_tokens=1_000_000, output_tokens=500_000,
            cost_usd=Decimal("7.50"))
        assert recommend._pair_cost_with(price, pair) == event_cost(
            input_tokens=1_000_000, output_tokens=500_000, price=price)
        # Exact Decimal math, no float drift.
        assert recommend._pair_cost_with(price, pair) == Decimal("7.50")

    def test_recommend_pair_cost_surfaces_missing_cached_price(self):
        """Consolidation behaviour: a pair needing a cached rate the catalog
        lacks raises instead of silently pricing cached tokens at $0."""
        price = _price("openai", "m", date(2026, 1, 1), None)
        pair = recommend.PairStats(
            application="chat", provider="openai", model="m",
            requests=100, input_tokens=1_000_000, output_tokens=0,
            cached_input_tokens=500_000, cost_usd=Decimal("2.00"))
        with pytest.raises(PriceNotFoundError):
            recommend._pair_cost_with(price, pair)


# ---------------------------------------------------------------------------
# Dashboard / P&L fixtures
# ---------------------------------------------------------------------------

def _mk_org_project(db):
    slug = f"p5-{uuid.uuid4().hex[:10]}"
    # Mirror signup: org row goes in under the pre-auth RLS bootstrap, then
    # the session is pinned to the org exactly as the auth dependency does.
    with deps.pre_auth_lookup(db):
        org = m.Organization(id=uuid.uuid4(), name="P5 Org", slug=slug)
        db.add(org)
        db.flush()
    deps.set_rls_org(db, org.id)
    user = m.User(id=uuid.uuid4(), org_id=org.id,
                  email=f"p5-{uuid.uuid4().hex[:8]}@x.io", password_hash="x")
    project = m.Project(id=uuid.uuid4(), org_id=org.id, name="P5 Project")
    db.add_all([user, project])
    db.flush()
    return org, user, project


def _mk_tenant(db, org, project, external_id, name, revenue):
    t = m.Tenant(id=uuid.uuid4(), org_id=org.id, project_id=project.id,
                 external_id=external_id, name=name,
                 monthly_revenue_usd=Decimal(revenue) if revenue is not None else None)
    db.add(t)
    db.flush()
    return t


def _mk_event(db, org, project, *, tenant_id, provider, model, application,
              at, cost):
    e = m.UsageEvent(
        id=uuid.uuid4(), org_id=org.id, project_id=project.id,
        source="event_api", provider=provider, model=model,
        application=application, tenant_id=tenant_id,
        occurred_at=at, input_tokens=1000, output_tokens=500,
        cost_calculated_usd=Decimal(cost) if cost is not None else None,
    )
    db.add(e)
    db.flush()
    return e


def _seed_events(db, org, project):
    """Tenants + priced events across two days. Returns None."""
    _mk_tenant(db, org, project, "acme", "Acme Corp", "1000.00")     # healthy
    _mk_tenant(db, org, project, "globex", "Globex", "100.00")       # margin killer
    _mk_tenant(db, org, project, "initech", "Initech", None)         # unknown revenue
    _mk_tenant(db, org, project, "quiet", "Quiet LLC", "500.00")     # no events

    now = _now()
    day1 = now - timedelta(days=2)
    day2 = now - timedelta(days=1)
    # Acme: $60 over 2 days, chat app, gpt-4.1-mini
    _mk_event(db, org, project, tenant_id="acme", provider="openai",
              model="gpt-4.1-mini", application="chat", at=day1, cost="40.00")
    _mk_event(db, org, project, tenant_id="acme", provider="openai",
              model="gpt-4.1-mini", application="chat", at=day2, cost="20.00")
    # Globex: $150 in 1 day, support app, gpt-4.1 (margin killer: 150 > 100 revenue)
    _mk_event(db, org, project, tenant_id="globex", provider="openai",
              model="gpt-4.1", application="support", at=day2, cost="150.00")
    # Initech: one unpriced event (no catalog price -> NULL cost)
    _mk_event(db, org, project, tenant_id="initech", provider="openai",
              model="mystery-model", application=None, at=day2, cost=None)
    db.flush()


@pytest.fixture()
def seeded(db):
    """Org/project with tenants and events (rollback-isolated, service tests)."""
    org, user, project = _mk_org_project(db)
    _seed_events(db, org, project)
    return org, user, project


@pytest.fixture()
def committed(db_url):
    """Write session that commits — for endpoint tests via the `client`
    fixture (which uses its own engine). Each test uses a fresh org, so
    committed rows cannot leak into other tests' assertions."""
    engine = create_engine(db_url, connect_args=({"check_same_thread": False}
                                                 if db_url.startswith("sqlite") else {}))
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _signup(client, org_name="P5 Org"):
    email = f"p5-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/api/v1/auth/signup", json={
        "email": email, "password": "correct-horse-9", "org_name": org_name})
    assert r.status_code == 201, r.text
    body = r.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return body, headers


class TestDashboard:
    def test_totals_and_unpriced(self, db, seeded):
        org, _, project = seeded
        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=30)
        assert d["days"] == 30
        assert d["total_cost_usd"] == Decimal("210.00")
        assert d["total_requests"] == 4
        assert d["unpriced_events"] == 1
        assert d["cost_basis"] == "calculated"

    def test_trend_sums_to_total_and_is_zero_filled(self, db, seeded):
        org, _, project = seeded
        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=30)
        assert len(d["trend"]) == 31  # 30-day window + today bucket
        assert sum(p["cost_usd"] for p in d["trend"]) == d["total_cost_usd"]
        assert sum(p["requests"] for p in d["trend"]) == d["total_requests"]
        assert all(p["cost_usd"] >= 0 for p in d["trend"])

    def test_by_model_order_and_share(self, db, seeded):
        org, _, project = seeded
        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=30)
        models = [r["model"] for r in d["by_model"]]
        assert models[0] == "gpt-4.1"  # $150, the cost driver
        assert d["by_model"][0]["cost_usd"] == Decimal("150.00")
        assert d["by_model"][0]["share_pct"] == Decimal("71.4")
        # Unpriced model still appears (cost 0) — surfaced, not hidden.
        assert "mystery-model" in models

    def test_by_application_unspecified_label(self, db, seeded):
        org, _, project = seeded
        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=30)
        apps = {r["application"]: r["cost_usd"] for r in d["by_application"]}
        assert apps["support"] == Decimal("150.00")
        assert apps["chat"] == Decimal("60.00")
        assert apps["Unspecified"] == Decimal("0")

    def test_top_tenants(self, db, seeded):
        org, _, project = seeded
        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=30)
        top = d["top_tenants"]
        assert top[0]["tenant_external_id"] == "globex"
        assert top[0]["tenant_name"] == "Globex"
        assert top[0]["cost_usd"] == Decimal("150.00")

    def test_window_respected(self, db, seeded):
        org, _, project = seeded
        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=1)
        # Only events from the trailing 24h count.
        assert d["total_requests"] <= 4
        assert d["total_cost_usd"] <= Decimal("210.00")

    def test_empty_project(self, db):
        org, _, project = _mk_org_project(db)
        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=30)
        assert d["total_cost_usd"] == Decimal("0")
        assert d["total_requests"] == 0
        assert d["by_model"] == [] and d["by_application"] == []
        assert d["top_tenants"] == []
        assert len(d["trend"]) == 31


class TestPnLStatuses:
    def test_statuses_and_margin_killer(self, db, seeded):
        org, _, project = seeded
        rows = {r["tenant_external_id"]: r
                for r in pnl_service.compute_pnl(db, org.id, project.id, days=30)}
        assert rows["acme"]["status"] == "healthy"
        assert rows["acme"]["margin_usd"] == Decimal("940.00")
        assert rows["globex"]["status"] == "margin_killer"
        assert rows["globex"]["margin_usd"] == Decimal("-50.00")
        assert rows["initech"]["status"] == "unknown"
        assert rows["initech"]["margin_usd"] is None
        assert rows["quiet"]["status"] == "healthy"  # no events, cost 0
        assert rows["quiet"]["ai_cost_usd"] == Decimal("0")

    def test_at_risk_boundary(self):
        # margin exactly 15% of revenue -> healthy; a cent less -> at_risk.
        assert pnl_service.tenant_status(Decimal("15.00"), Decimal("100.00")) == "healthy"
        assert pnl_service.tenant_status(Decimal("14.99"), Decimal("100.00")) == "at_risk"
        assert pnl_service.tenant_status(Decimal("-0.01"), Decimal("100.00")) == "margin_killer"
        assert pnl_service.tenant_status(Decimal("10"), None) == "unknown"
        assert pnl_service.tenant_status(Decimal("10"), Decimal("0")) == "unknown"


class TestCostBasisHonesty:
    def test_reported_costs_never_feed_dashboard_or_pnl(self, db, seeded):
        """Launch honesty invariant: every analytics figure derives from
        cost_calculated_usd — provider-reported costs are never inputs.
        Poisoning cost_reported_usd with absurd values must not move any
        dashboard total or P&L margin."""
        org, _, project = seeded
        db.query(m.UsageEvent).filter_by(org_id=org.id).update(
            {"cost_reported_usd": Decimal("999999.99")},
            synchronize_session=False,
        )
        db.flush()

        d = dashboard_service.compute_dashboard(db, org.id, project.id, days=30)
        assert d["total_cost_usd"] == Decimal("210.00")
        assert d["cost_basis"] == "calculated"
        assert all(p["cost_usd"] < Decimal("1000000") for p in d["trend"])

        rows = {r["tenant_external_id"]: r
                for r in pnl_service.compute_pnl(db, org.id, project.id, days=30)}
        assert rows["acme"]["ai_cost_usd"] == Decimal("60.00")
        assert rows["acme"]["margin_usd"] == Decimal("940.00")
        assert rows["globex"]["ai_cost_usd"] == Decimal("150.00")
        assert rows["globex"]["margin_usd"] == Decimal("-50.00")


class TestPnLUnpricedHonesty:
    """Launch honesty invariant: a tenant whose events are unpriced (NULL
    calculated cost) must never silently read as $0 AI cost in the P&L.
    The row carries an explicit unpriced_events count instead."""

    def _seed_unpriced_tenant(self, db, org=None, project=None):
        if org is None or project is None:
            org, _, project = _mk_org_project(db)
        _mk_tenant(db, org, project, "pricedco", "Priced Co", "1000.00")
        _mk_tenant(db, org, project, "mysteryco", "Mystery Co", "500.00")
        now = _now()
        _mk_event(db, org, project, tenant_id="pricedco", provider="openai",
                  model="gpt-4.1-mini", application="chat",
                  at=now - timedelta(days=1), cost="42.00")
        # Mystery Co: two events, no catalog price -> NULL cost (unknown, not $0)
        _mk_event(db, org, project, tenant_id="mysteryco", provider="openai",
                  model="mystery-model", application="chat",
                  at=now - timedelta(days=1), cost=None)
        _mk_event(db, org, project, tenant_id="mysteryco", provider="openai",
                  model="mystery-model", application="chat",
                  at=now - timedelta(hours=1), cost=None)
        db.flush()
        return org, project

    def test_unpriced_events_are_explicit_not_silent(self, db):
        org, project = self._seed_unpriced_tenant(db)
        rows = {r["tenant_external_id"]: r
                for r in pnl_service.compute_pnl(db, org.id, project.id, days=30)}
        assert rows["pricedco"]["ai_cost_usd"] == Decimal("42.00")
        assert rows["pricedco"]["unpriced_events"] == 0
        # Mystery Co's cost is unknown, not zero — the row says so explicitly.
        assert rows["mysteryco"]["ai_cost_usd"] == Decimal("0")
        assert rows["mysteryco"]["unpriced_events"] == 2

    def test_pnl_endpoint_exposes_unpriced_events(self, client, committed):
        from app.schemas import projects as project_schemas

        body, headers = _signup(client)
        project_id, org_id = body["project"]["id"], body["org"]["id"]
        # Standalone session: pin the org's RLS context like the app does.
        deps.set_rls_org(committed, uuid.UUID(org_id))
        org = committed.query(m.Organization).filter_by(id=uuid.UUID(org_id)).one()
        project = committed.query(m.Project).filter_by(id=uuid.UUID(project_id)).one()
        self._seed_unpriced_tenant(committed, org, project)
        committed.commit()

        r = client.get(f"/api/v1/projects/{project_id}/pnl?days=30", headers=headers)
        assert r.status_code == 200, r.text
        parsed = project_schemas.ProjectPnLResponse(**r.json())
        rows = {t.tenant_external_id: t for t in parsed.tenants}
        assert rows["mysteryco"].ai_cost_usd == Decimal("0")
        assert rows["mysteryco"].unpriced_events == 2
        assert rows["pricedco"].unpriced_events == 0


class TestDashboardEndpoint:
    def test_dashboard_round_trip_matches_service(self, client, committed):
        from app.schemas import projects as project_schemas

        body, headers = _signup(client)
        project_id, org_id = body["project"]["id"], body["org"]["id"]
        # Standalone session: pin the org's RLS context like the app does.
        deps.set_rls_org(committed, uuid.UUID(org_id))
        org = committed.query(m.Organization).filter_by(id=uuid.UUID(org_id)).one()
        project = committed.query(m.Project).filter_by(id=uuid.UUID(project_id)).one()
        _seed_events(committed, org, project)
        committed.commit()

        r = client.get(f"/api/v1/projects/{project_id}/dashboard?days=30",
                       headers=headers)
        assert r.status_code == 200, r.text
        parsed = project_schemas.ProjectDashboardResponse(**r.json())
        assert parsed.data_label == "customer"
        assert parsed.cost_basis == "calculated"
        assert parsed.total_cost_usd == Decimal("210.00")
        assert parsed.total_requests == 4
        assert parsed.unpriced_events == 1
        # Field-for-field agreement with the shared service.
        # commit() drops the SET LOCAL RLS context, so re-pin first.
        deps.set_rls_org(committed, uuid.UUID(org_id))
        svc = dashboard_service.compute_dashboard(
            committed, uuid.UUID(org_id), uuid.UUID(project_id), days=30)
        assert parsed.total_cost_usd == svc["total_cost_usd"]
        assert [p.cost_usd for p in parsed.trend] == [p["cost_usd"] for p in svc["trend"]]
        assert [b.model for b in parsed.by_model] == [b["model"] for b in svc["by_model"]]

    def test_dashboard_rejects_bad_days(self, client, committed):
        body, headers = _signup(client)
        project_id = body["project"]["id"]
        r = client.get(f"/api/v1/projects/{project_id}/dashboard?days=14",
                       headers=headers)
        assert r.status_code == 400

    def test_dashboard_cross_org_404(self, client, committed):
        body_a, _ = _signup(client, org_name="P5 Org A")
        body_b, headers_b = _signup(client, org_name="P5 Org B")
        r = client.get(f"/api/v1/projects/{body_a['project']['id']}/dashboard",
                       headers=headers_b)
        assert r.status_code == 404
