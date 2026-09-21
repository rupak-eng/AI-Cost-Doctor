"""Phase 6 tests: deterministic anomaly detection — spend spikes, new
expensive model adoption, and margin-killer emergence — plus the anomalies
API (list with unread_count, acknowledge, cross-org isolation).

All against the local test DB (Postgres when available, SQLite fallback).
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
from app.services import anomalies as anomalies_service
from app.services.anomalies import (
    MARGIN_KILLER_EMERGENCE,
    NEW_EXPENSIVE_MODEL,
    SPEND_SPIKE,
)
from app.services.costing import Price, ensure_catalog_in_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mk_org_project(db):
    slug = f"p6-{uuid.uuid4().hex[:10]}"
    # Mirror signup: org row goes in under the pre-auth RLS bootstrap, then
    # the session is pinned to the org exactly as the auth dependency does.
    with deps.pre_auth_lookup(db):
        org = m.Organization(id=uuid.uuid4(), name="P6 Org", slug=slug)
        db.add(org)
        db.flush()
    deps.set_rls_org(db, org.id)
    user = m.User(id=uuid.uuid4(), org_id=org.id,
                  email=f"p6-{uuid.uuid4().hex[:8]}@x.io", password_hash="x")
    project = m.Project(id=uuid.uuid4(), org_id=org.id, name="P6 Project")
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


def _price(provider, model, rate_sum, effective_from=date(2025, 1, 1)):
    half = (Decimal(rate_sum) / 2).quantize(Decimal("0.000001"))
    return Price(
        provider=provider, model=model,
        input_usd_per_1m=half, output_usd_per_1m=half,
        cached_input_usd_per_1m=None, reasoning_usd_per_1m=None,
        effective_from=effective_from, effective_to=None,
    )


def _seed_catalog(db):
    """Controlled catalog: cheap(2) / mid(4) / pricey(20) / bargain(1)."""
    ensure_catalog_in_db(db, catalog=[
        _price("openai", "cheap-model", "2"),
        _price("openai", "mid-model", "4"),
        _price("openai", "pricey-model", "20"),
        _price("openai", "bargain-model", "1"),
    ])


def _seed_spike_baseline(db, org, project, tenant_id, daily_cost="10.00",
                         days=14):
    now = _now()
    for i in range(1, days + 1):
        _mk_event(db, org, project, tenant_id=tenant_id, provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=i, hours=1), cost=daily_cost)
    db.flush()


@pytest.fixture()
def org_project(db):
    org, user, project = _mk_org_project(db)
    return org, user, project


# ---------------------------------------------------------------------------
# Detector 1: spend spike
# ---------------------------------------------------------------------------

class TestSpendSpike:
    def _tenant(self, db, org, project):
        return _mk_tenant(db, org, project, "spike-co", "Spike Co", None)

    def _spike_findings(self, db, org, project, tenant_id="spike-co"):
        created = anomalies_service.detect_anomalies(db, org.id, project.id)
        return [r for r in created
                if r.detector == SPEND_SPIKE and r.dimension_value == tenant_id]

    def test_spike_fires_above_ratio_and_delta(self, db, org_project):
        org, _, project = org_project
        self._tenant(db, org, project)
        _seed_spike_baseline(db, org, project, "spike-co")  # $10/day x 14
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="40.00")  # 4x, +$30
        rows = self._spike_findings(db, org, project)
        assert len(rows) == 1
        row = rows[0]
        assert row.severity == "warning"  # 4x < 5x, +$30 < $500
        assert row.baseline_usd == Decimal("10.00")
        assert row.observed_usd == Decimal("40.00")
        assert row.abs_delta_usd == Decimal("30.00")
        assert row.change_pct == Decimal("300.0000")
        assert row.dimension == "tenant"
        assert "spend spike" in row.evidence["title"].lower()

    def test_spike_critical_at_5x(self, db, org_project):
        org, _, project = org_project
        self._tenant(db, org, project)
        _seed_spike_baseline(db, org, project, "spike-co")
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="60.00")  # 6x, +$50
        rows = self._spike_findings(db, org, project)
        assert len(rows) == 1
        assert rows[0].severity == "critical"

    def test_spike_below_ratio_no_fire(self, db, org_project):
        org, _, project = org_project
        self._tenant(db, org, project)
        _seed_spike_baseline(db, org, project, "spike-co", daily_cost="100.00")
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="249.00")  # 2.49x
        assert self._spike_findings(db, org, project) == []

    def test_spike_above_ratio_fires(self, db, org_project):
        org, _, project = org_project
        self._tenant(db, org, project)
        _seed_spike_baseline(db, org, project, "spike-co", daily_cost="100.00")
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="251.00")  # 2.51x, +$151
        rows = self._spike_findings(db, org, project)
        assert len(rows) == 1

    def test_spike_below_delta_floor_no_fire(self, db, org_project):
        org, _, project = org_project
        self._tenant(db, org, project)
        _seed_spike_baseline(db, org, project, "spike-co")  # $10/day
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="30.00")  # 3x but +$20
        assert self._spike_findings(db, org, project) == []

    def test_spike_needs_baseline_history(self, db, org_project):
        org, _, project = org_project
        self._tenant(db, org, project)
        _seed_spike_baseline(db, org, project, "spike-co", days=3)
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="500.00")
        assert self._spike_findings(db, org, project) == []

    def test_spike_zero_baseline_fires(self, db, org_project):
        org, _, project = org_project
        self._tenant(db, org, project)
        _seed_spike_baseline(db, org, project, "spike-co", daily_cost="0.00")
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="30.00")
        rows = self._spike_findings(db, org, project)
        assert len(rows) == 1
        assert rows[0].change_pct is None  # no baseline → no pct


# ---------------------------------------------------------------------------
# Detector 2: new expensive model adoption
# ---------------------------------------------------------------------------

class TestNewExpensiveModel:
    def _history(self, db, org, project, tenant_id="newmo-co", models=("cheap-model", "mid-model")):
        _mk_tenant(db, org, project, tenant_id, "Newmo Co", None)
        now = _now()
        for i, model in enumerate(models):
            _mk_event(db, org, project, tenant_id=tenant_id, provider="openai",
                      model=model, application="chat",
                      at=now - timedelta(days=10 + i), cost="5.00")
        db.flush()

    def _model_findings(self, db, org, project):
        created = anomalies_service.detect_anomalies(db, org.id, project.id)
        return [r for r in created if r.detector == NEW_EXPENSIVE_MODEL]

    def test_new_expensive_model_fires_with_run_rate(self, db, org_project):
        org, _, project = org_project
        _seed_catalog(db)
        self._history(db, org, project)  # project median rate = (2+4)/2 = 3
        now = _now()
        for i in range(3):
            _mk_event(db, org, project, tenant_id="newmo-co", provider="openai",
                      model="pricey-model", application="chat",
                      at=now - timedelta(days=i, hours=2), cost="20.00")
        rows = self._model_findings(db, org, project)
        assert len(rows) == 1
        row = rows[0]
        assert row.severity == "warning"  # $600/mo run-rate < $1000
        assert row.evidence["model"] == "pricey-model"
        assert Decimal(row.evidence["projected_monthly_run_rate_usd"]) == Decimal("600")
        assert Decimal(row.evidence["project_median_rate_sum_per_1m_usd"]) == Decimal("3")

    def test_new_model_below_run_rate_no_fire(self, db, org_project):
        org, _, project = org_project
        _seed_catalog(db)
        self._history(db, org, project)
        _mk_event(db, org, project, tenant_id="newmo-co", provider="openai",
                  model="pricey-model", application="chat",
                  at=_now() - timedelta(days=1), cost="3.00")  # $30/mo run-rate
        assert self._model_findings(db, org, project) == []

    def test_new_cheap_model_no_fire(self, db, org_project):
        org, _, project = org_project
        _seed_catalog(db)
        self._history(db, org, project)
        _mk_event(db, org, project, tenant_id="newmo-co", provider="openai",
                  model="bargain-model", application="chat",
                  at=_now() - timedelta(days=1), cost="100.00")
        assert self._model_findings(db, org, project) == []

    def test_previously_used_model_no_fire(self, db, org_project):
        org, _, project = org_project
        _seed_catalog(db)
        self._history(db, org, project)
        now = _now()
        _mk_event(db, org, project, tenant_id="newmo-co", provider="openai",
                  model="pricey-model", application="chat",
                  at=now - timedelta(days=10), cost="50.00")  # used before
        _mk_event(db, org, project, tenant_id="newmo-co", provider="openai",
                  model="pricey-model", application="chat",
                  at=now - timedelta(days=1), cost="60.00")
        assert self._model_findings(db, org, project) == []


# ---------------------------------------------------------------------------
# Detector 3: margin-killer emergence
# ---------------------------------------------------------------------------

class TestMarginKillerEmergence:
    def _findings(self, db, org, project):
        created = anomalies_service.detect_anomalies(db, org.id, project.id)
        return [r for r in created if r.detector == MARGIN_KILLER_EMERGENCE]

    def test_emergence_fires(self, db, org_project):
        org, _, project = org_project
        _mk_tenant(db, org, project, "margin-co", "Margin Co", "1000.00")
        now = _now()
        _mk_event(db, org, project, tenant_id="margin-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=45), cost="100.00")   # prev: healthy
        _mk_event(db, org, project, tenant_id="margin-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=1), cost="1200.00")    # cur: killer
        rows = self._findings(db, org, project)
        assert len(rows) == 1
        row = rows[0]
        assert row.severity == "critical"
        assert row.dimension_value == "margin-co"
        assert row.evidence["previous_status"] == "healthy"
        assert row.evidence["current_status"] == "margin_killer"
        assert row.baseline_usd == Decimal("900.00")
        assert row.observed_usd == Decimal("-200.00")

    def test_no_emergence_when_already_killer(self, db, org_project):
        org, _, project = org_project
        _mk_tenant(db, org, project, "margin-co", "Margin Co", "1000.00")
        now = _now()
        _mk_event(db, org, project, tenant_id="margin-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=45), cost="1200.00")
        _mk_event(db, org, project, tenant_id="margin-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=1), cost="1300.00")
        assert self._findings(db, org, project) == []

    def test_no_emergence_without_revenue(self, db, org_project):
        org, _, project = org_project
        _mk_tenant(db, org, project, "margin-co", "Margin Co", None)
        now = _now()
        _mk_event(db, org, project, tenant_id="margin-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=1), cost="5000.00")
        assert self._findings(db, org, project) == []


# ---------------------------------------------------------------------------
# Idempotency + listing
# ---------------------------------------------------------------------------

class TestDetectionIdempotent:
    def test_repeat_detection_no_duplicates(self, db, org_project):
        org, _, project = org_project
        _mk_tenant(db, org, project, "spike-co", "Spike Co", None)
        _seed_spike_baseline(db, org, project, "spike-co")
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="40.00")
        first = anomalies_service.detect_anomalies(db, org.id, project.id)
        second = anomalies_service.detect_anomalies(db, org.id, project.id)
        assert len(first) >= 1
        assert second == []
        count = db.query(m.CostAnomaly).filter_by(project_id=project.id).count()
        assert count == len(first)

    def test_list_severity_order_and_unread(self, db, org_project):
        org, _, project = org_project
        _mk_tenant(db, org, project, "spike-co", "Spike Co", None)
        _seed_spike_baseline(db, org, project, "spike-co")
        _mk_event(db, org, project, tenant_id="spike-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=_now() - timedelta(hours=1), cost="40.00")  # warning spike
        _mk_tenant(db, org, project, "margin-co", "Margin Co", "1000.00")
        now = _now()
        _mk_event(db, org, project, tenant_id="margin-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=45), cost="100.00")    # was healthy
        _mk_event(db, org, project, tenant_id="margin-co", provider="openai",
                  model="cheap-model", application="chat",
                  at=now - timedelta(days=1), cost="1200.00")    # now killer
        result = anomalies_service.list_anomalies(db, org.id, project.id, days=30)
        assert result["unread_count"] == len(result["anomalies"]) >= 2
        severities = [a["severity"] for a in result["anomalies"]]
        assert "critical" in severities and "warning" in severities
        assert severities == sorted(
            severities,
            key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s])


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.fixture()
def committed(db_url):
    engine = create_engine(db_url, connect_args=({"check_same_thread": False}
                                                 if db_url.startswith("sqlite") else {}))
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _signup(client, org_name="P6 Org"):
    email = f"p6-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/api/v1/auth/signup", json={
        "email": email, "password": "correct-horse-9", "org_name": org_name})
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def _seed_spike_for_api(committed, org_id, project_id):
    # The standalone session needs the org's RLS context, exactly as the
    # authenticated request path sets it.
    deps.set_rls_org(committed, org_id)
    org = committed.query(m.Organization).filter_by(id=org_id).one()
    project = committed.query(m.Project).filter_by(id=project_id).one()
    _mk_tenant(committed, org, project, "spike-co", "Spike Co", None)
    _seed_spike_baseline(committed, org, project, "spike-co")
    _mk_event(committed, org, project, tenant_id="spike-co", provider="openai",
              model="cheap-model", application="chat",
              at=_now() - timedelta(hours=1), cost="40.00")
    committed.commit()


class TestAnomaliesApi:
    def test_list_round_trip(self, client, committed):
        from app.schemas import projects as project_schemas

        body, headers = _signup(client)
        project_id, org_id = body["project"]["id"], body["org"]["id"]
        _seed_spike_for_api(committed, uuid.UUID(org_id), uuid.UUID(project_id))

        r = client.get(f"/api/v1/projects/{project_id}/anomalies?days=30",
                       headers=headers)
        assert r.status_code == 200, r.text
        parsed = project_schemas.ProjectAnomaliesResponse(**r.json())
        assert parsed.data_label == "customer"
        assert parsed.days == 30
        assert parsed.unread_count == len(parsed.anomalies) >= 1
        tenant_rows = [a for a in parsed.anomalies
                       if a.detector == "spend_spike" and a.dimension == "tenant"]
        assert len(tenant_rows) == 1
        row = tenant_rows[0]
        assert row.investigate_tenant_external_id == "spike-co"
        assert row.tenant_name == "Spike Co"
        assert row.title and row.detail

    def test_quiet_project_empty_state(self, client, committed):
        body, headers = _signup(client, org_name="P6 Quiet")
        r = client.get(f"/api/v1/projects/{body['project']['id']}/anomalies",
                       headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["anomalies"] == [] and data["unread_count"] == 0

    def test_acknowledge_flow(self, client, committed):
        body, headers = _signup(client, org_name="P6 Ack")
        project_id, org_id = body["project"]["id"], body["org"]["id"]
        _seed_spike_for_api(committed, uuid.UUID(org_id), uuid.UUID(project_id))

        r = client.get(f"/api/v1/projects/{project_id}/anomalies", headers=headers)
        anomaly_id = r.json()["anomalies"][0]["id"]
        assert r.json()["unread_count"] >= 1

        r = client.post(
            f"/api/v1/projects/{project_id}/anomalies/{anomaly_id}/acknowledge",
            headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "acknowledged"

        # Acknowledged anomalies leave the unread count and don't re-fire.
        r = client.get(f"/api/v1/projects/{project_id}/anomalies", headers=headers)
        by_id = {a["id"]: a for a in r.json()["anomalies"]}
        assert by_id[anomaly_id]["status"] == "acknowledged"
        assert r.json()["unread_count"] == len(
            [a for a in r.json()["anomalies"] if a["status"] == "open"])

    def test_acknowledge_unknown_id_404(self, client, committed):
        body, headers = _signup(client, org_name="P6 Ack404")
        r = client.post(
            f"/api/v1/projects/{body['project']['id']}/anomalies/{uuid.uuid4()}/acknowledge",
            headers=headers)
        assert r.status_code == 404

    def test_cross_org_isolation(self, client, committed):
        body_a, _ = _signup(client, org_name="P6 Org A")
        body_b, headers_b = _signup(client, org_name="P6 Org B")
        _seed_spike_for_api(committed, uuid.UUID(body_a["org"]["id"]),
                            uuid.UUID(body_a["project"]["id"]))

        r = client.get(f"/api/v1/projects/{body_a['project']['id']}/anomalies",
                       headers=headers_b)
        assert r.status_code == 404

        # Org A reads its own anomaly id; org B cannot acknowledge it.
        r = client.get(f"/api/v1/projects/{body_a['project']['id']}/anomalies",
                       headers={"Authorization": f"Bearer {body_a['access_token']}"})
        anomaly_id = r.json()["anomalies"][0]["id"]
        r = client.post(
            f"/api/v1/projects/{body_a['project']['id']}/anomalies/{anomaly_id}/acknowledge",
            headers=headers_b)
        assert r.status_code == 404

    def test_rejects_bad_days(self, client, committed):
        body, headers = _signup(client, org_name="P6 Days")
        r = client.get(f"/api/v1/projects/{body['project']['id']}/anomalies?days=14",
                       headers=headers)
        assert r.status_code == 400
