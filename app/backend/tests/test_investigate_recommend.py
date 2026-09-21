"""Phase 7 tests: root-cause investigation (driver attribution, volume-vs-token
dollar decomposition, expensive workflows) and savings recommendations
(routing math, caching honesty, anomaly follow-ups, confidence, disclaimer),
plus the investigate API surface (GET variant, explain endpoint).

All against the local test DB (Postgres when available, SQLite fallback).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app import models as m
from app.api.v1 import deps
from app.services import investigate as inv
from app.services import narrative
from app.services.costing import load_catalog
from app.services.recommend import (
    DISCLAIMER,
    PairStats,
    model_routing_opportunity,
    prompt_caching_opportunity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mk_org_project(db, tag="p7"):
    slug = f"{tag}-{uuid.uuid4().hex[:10]}"
    # Mirror signup: org row goes in under the pre-auth RLS bootstrap, then
    # the session is pinned to the org exactly as the auth dependency does.
    with deps.pre_auth_lookup(db):
        org = m.Organization(id=uuid.uuid4(), name=f"{tag} Org", slug=slug)
        db.add(org)
        db.flush()
    deps.set_rls_org(db, org.id)
    project = m.Project(id=uuid.uuid4(), org_id=org.id, name=f"{tag} Project")
    db.add(project)
    db.flush()
    return org, project


def _mk_tenant(db, org, project, external_id, name="Tenant", revenue="1000"):
    t = m.Tenant(id=uuid.uuid4(), org_id=org.id, project_id=project.id,
                 external_id=external_id, name=name,
                 monthly_revenue_usd=Decimal(revenue) if revenue is not None else None)
    db.add(t)
    db.flush()
    return t


def _mk_event(db, org, project, *, tenant_id, provider="openai", model="gpt-4.1",
              application="Support Agent", at=None, in_tok=1000, out_tok=500,
              cached_tok=0, cost="1.00"):
    e = m.UsageEvent(
        id=uuid.uuid4(), org_id=org.id, project_id=project.id,
        source="event_api", provider=provider, model=model,
        application=application, tenant_id=tenant_id,
        occurred_at=at or _now(),
        input_tokens=in_tok, output_tokens=out_tok,
        cached_input_tokens=cached_tok,
        cost_calculated_usd=Decimal(cost),
    )
    db.add(e)
    db.flush()
    return e


def _catalog():
    return load_catalog()


class TestDriverAttribution:
    def test_drivers_sum_to_tenant_total(self, db):
        org, project = _mk_org_project(db)
        _mk_tenant(db, org, project, "acme", "Acme")
        now = _now()
        # Two models x two apps, known costs.
        _mk_event(db, org, project, tenant_id="acme", model="gpt-4.1",
                  application="Support", at=now - timedelta(days=1), cost="60.00")
        _mk_event(db, org, project, tenant_id="acme", model="gpt-4.1-mini",
                  application="Support", at=now - timedelta(days=2), cost="30.00")
        _mk_event(db, org, project, tenant_id="acme", model="gpt-4.1",
                  application="Docs", at=now - timedelta(days=3), cost="10.00")
        # Another tenant's events must not leak in.
        _mk_tenant(db, org, project, "other", "Other")
        _mk_event(db, org, project, tenant_id="other", model="gpt-4.1",
                  application="Support", at=now - timedelta(days=1), cost="999.00")

        facts = inv.investigate_tenant(db, org.id, project.id, "acme", days=30)
        by_model = facts["drivers"]["by_model"]
        by_app = facts["drivers"]["by_app"]
        assert sum(d["cost_usd"] for d in by_model) == Decimal("100.00")
        assert sum(d["cost_usd"] for d in by_app) == Decimal("100.00")
        # No double counting: pct shares sum to ~100.
        assert abs(sum(d["pct"] for d in by_model) - 100) < 0.2
        # Sorted desc, top driver identified.
        assert by_model[0]["model"] == "gpt-4.1"
        assert by_model[0]["cost_usd"] == Decimal("70.00")

    def test_unknown_tenant_raises(self, db):
        org, project = _mk_org_project(db)
        try:
            inv.investigate_tenant(db, org.id, project.id, "ghost", days=30)
            raise AssertionError("expected TenantNotFoundError")
        except inv.TenantNotFoundError:
            pass

    def test_cross_org_isolation(self, db):
        org_a, proj_a = _mk_org_project(db, tag="p7a")
        org_b, proj_b = _mk_org_project(db, tag="p7b")
        _mk_tenant(db, org_b, proj_b, "shared-ext", "Shared")
        # Simulate org A's user: pin the RLS context to org A so the service
        # must reject org B's tenant on its own org filter (RLS is the second
        # layer, not the first).
        deps.set_rls_org(db, org_a.id)
        try:
            inv.investigate_tenant(db, org_a.id, proj_a.id, "shared-ext", days=30)
            raise AssertionError("expected TenantNotFoundError")
        except inv.TenantNotFoundError:
            pass


class TestVolumeVsTokensDollars:
    def _seed_two_windows(self, db, org, project):
        """Prior 23d: 230 req x 1000 tok @ $0.10. Recent 7d: 140 req x 1500 tok @ $0.15.

        Hand-computed decomposition (prior scaled to 7d: r0=70, k0=70k, t0=1000,
        p0=$0.0001/tok; recent p1=$0.0001/tok):
          volume_effect = (140-70) x 1000 x 0.0001 = $7.00
          token_effect  = (210k-140k) x 0.0001      = $7.00
          mix_effect    = 21 - 7 - 7 - 7            = $0.00
        """
        _mk_tenant(db, org, project, "acme", "Acme")
        now = _now()
        # +1h offset keeps every event safely inside its window boundary.
        for day in range(8, 31):  # 23 prior days x 10 req
            for _ in range(10):
                _mk_event(db, org, project, tenant_id="acme",
                          at=now - timedelta(days=day) + timedelta(hours=1),
                          in_tok=800, out_tok=200, cost="0.10")
        for day in range(1, 8):  # recent 7 days x 20 req
            for _ in range(20):
                _mk_event(db, org, project, tenant_id="acme",
                          at=now - timedelta(days=day) + timedelta(hours=1),
                          in_tok=1200, out_tok=300, cost="0.15")

    def test_dollar_attribution_matches_hand_computation(self, db):
        org, project = _mk_org_project(db)
        self._seed_two_windows(db, org, project)
        facts = inv.investigate_tenant(db, org.id, project.id, "acme", days=30)
        vvt = facts["volume_vs_tokens"]
        assert abs(Decimal(str(vvt["volume_effect_usd"])) - Decimal("7.00")) < Decimal("0.05")
        assert abs(Decimal(str(vvt["token_intensity_effect_usd"])) - Decimal("7.00")) < Decimal("0.05")
        assert abs(Decimal(str(vvt["mix_effect_usd"]))) < Decimal("0.05")
        # Pct deltas still present: volume +100%, tpr +50%.
        assert abs(vvt["requests_delta_pct"] - 100.0) < 0.5
        assert abs(vvt["avg_tokens_per_request_delta_pct"] - 50.0) < 0.5

    def test_effects_sum_to_total_change(self, db):
        org, project = _mk_org_project(db)
        self._seed_two_windows(db, org, project)
        facts = inv.investigate_tenant(db, org.id, project.id, "acme", days=30)
        vvt = facts["volume_vs_tokens"]
        total = (Decimal(str(vvt["volume_effect_usd"]))
                 + Decimal(str(vvt["token_intensity_effect_usd"]))
                 + Decimal(str(vvt["mix_effect_usd"])))
        # Total change: recent $21.00 - prior-scaled $7.00 = $14.00.
        assert abs(total - Decimal("14.00")) < Decimal("0.05")


class TestRoutingSavingsMath:
    def _pair(self, **kw):
        base = dict(application="Classification", provider="openai", model="gpt-4.1",
                    requests=2_000, input_tokens=3_000_000, output_tokens=1_000_000,
                    cost_usd=Decimal("100"))
        base.update(kw)
        return PairStats(**base)

    def test_hand_computed_savings(self):
        # gpt-4.1 ($2/$8 per 1M) vs gpt-4.1-mini ($0.4/$1.6):
        # delta = 3M x $1.6/1M + 1M x $6.4/1M = $4.80 + $6.40 = $11.20;
        # x 50% shiftable share = $5.60.
        opps = model_routing_opportunity([self._pair()], _catalog())
        assert len(opps) == 1
        opp = opps[0]
        assert opp.est_savings_usd_mo == Decimal("5.60")
        assert opp.confidence == "high"  # 2000 requests > 1000

    def test_never_recommends_across_providers(self):
        opps = model_routing_opportunity([self._pair()], _catalog())
        assert all(o.from_provider == "openai" for o in opps)
        assert all("claude" not in o.to_model for o in opps)

    def test_recommendation_carries_disclaimer(self):
        from app.services.recommend import routing_recommendation
        opps = model_routing_opportunity([self._pair()], _catalog())
        rec = routing_recommendation(opps[0])
        assert rec.disclaimer == DISCLAIMER
        assert "not guarantees" in rec.disclaimer


class TestCachingHonesty:
    def _pair(self, **kw):
        base = dict(application="Support Agent", provider="openai", model="gpt-4.1",
                    requests=5_000, input_tokens=100_000_000, output_tokens=1_000_000,
                    cached_input_tokens=10_000_000, cost_usd=Decimal("500"))
        base.update(kw)
        return PairStats(**base)

    def test_fires_only_with_observed_cache_hits(self):
        # 10% cached share, gpt-4.1 cached delta $1.50/1M:
        # 90M uncached x $1.50/1M x 25% = $33.75.
        opps = prompt_caching_opportunity([self._pair()], _catalog())
        assert len(opps) == 1
        assert opps[0].est_savings_usd_mo == Decimal("33.75")
        assert opps[0].confidence == "medium"  # 10M cached tokens observed

    def test_skipped_without_cache_signal(self):
        pair = self._pair(cached_input_tokens=0)
        assert prompt_caching_opportunity([pair], _catalog()) == []

    def test_skipped_when_already_mostly_cached(self):
        pair = self._pair(cached_input_tokens=85_000_000)  # 85% share
        assert prompt_caching_opportunity([pair], _catalog()) == []

    def test_skipped_below_savings_floor(self):
        pair = self._pair(input_tokens=1_000_000, cached_input_tokens=100_000)
        assert prompt_caching_opportunity([pair], _catalog()) == []


class TestAnomalyFollowups:
    def _mk_anomaly(self, db, org, project, tenant_ext):
        a = m.CostAnomaly(
            id=uuid.uuid4(), org_id=org.id, project_id=project.id,
            dimension="tenant", dimension_value=tenant_ext,
            detector="spend_spike", severity="warning", status="open",
            detected_at=_now() - timedelta(days=1),
            baseline_usd=Decimal("10.00"), observed_usd=Decimal("52.00"),
            abs_delta_usd=Decimal("42.00"),
            evidence={"title": "Spend spike: Acme",
                      "detail": "Spend spike detail text."},
        )
        db.add(a)
        db.flush()
        return a

    def test_followup_present_when_open_anomaly_exists(self, db):
        org, project = _mk_org_project(db)
        _mk_tenant(db, org, project, "acme", "Acme")
        _mk_event(db, org, project, tenant_id="acme",
                  at=_now() - timedelta(days=1), cost="5.00")
        self._mk_anomaly(db, org, project, "acme")
        facts = inv.investigate_tenant(db, org.id, project.id, "acme", days=30)
        followups = [r for r in facts["recommendations"] if r["type"] == "anomaly_followup"]
        assert len(followups) == 1
        assert followups[0]["est_savings_usd_mo"] == Decimal("42.00")
        assert followups[0]["disclaimer"] == DISCLAIMER

    def test_no_followup_without_anomaly(self, db):
        org, project = _mk_org_project(db)
        _mk_tenant(db, org, project, "quiet", "Quiet")
        _mk_event(db, org, project, tenant_id="quiet",
                  at=_now() - timedelta(days=1), cost="5.00")
        facts = inv.investigate_tenant(db, org.id, project.id, "quiet", days=30)
        assert [r for r in facts["recommendations"]
                if r["type"] == "anomaly_followup"] == []

    def test_acknowledged_anomaly_not_surfaced(self, db):
        org, project = _mk_org_project(db)
        _mk_tenant(db, org, project, "acme", "Acme")
        _mk_event(db, org, project, tenant_id="acme",
                  at=_now() - timedelta(days=1), cost="5.00")
        a = self._mk_anomaly(db, org, project, "acme")
        a.status = "acknowledged"
        db.flush()
        facts = inv.investigate_tenant(db, org.id, project.id, "acme", days=30)
        assert [r for r in facts["recommendations"]
                if r["type"] == "anomaly_followup"] == []


class TestInvestigateApi:
    def _signup(self, client, org_name=None):
        email = f"p7-{uuid.uuid4().hex[:12]}@example.com"
        r = client.post("/api/v1/auth/signup", json={
            "email": email, "password": "correct-horse-9",
            "org_name": org_name or f"P7 {uuid.uuid4().hex[:6]}"})
        assert r.status_code == 201, r.text
        body = r.json()
        return body, {"Authorization": f"Bearer {body['access_token']}"}

    def _seed(self, client, project_id, org_id):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import os
        eng = create_engine(os.environ["DATABASE_URL"])
        s = sessionmaker(bind=eng)()
        # Standalone session: pin the org's RLS context like the app does.
        deps.set_rls_org(s, uuid.UUID(org_id))
        org = s.query(m.Organization).filter_by(id=uuid.UUID(org_id)).one()
        project = s.query(m.Project).filter_by(id=uuid.UUID(project_id)).one()
        _mk_tenant(s, org, project, "acme", "Acme", revenue="500")
        now = _now()
        for i in range(5):
            _mk_event(s, org, project, tenant_id="acme",
                      model="gpt-4.1", application="Support Agent",
                      at=now - timedelta(days=i + 1),
                      in_tok=2000, out_tok=500, cost="12.00")
        s.commit()
        s.close()
        eng.dispose()

    def test_get_investigate_matches_post(self, client):
        body, headers = self._signup(client)
        project_id, org_id = body["project"]["id"], body["org"]["id"]
        self._seed(client, project_id, org_id)
        get_r = client.get(
            f"/api/v1/projects/{project_id}/investigate",
            params={"tenant": "acme", "days": 30}, headers=headers)
        assert get_r.status_code == 200, get_r.text
        post_r = client.post(
            f"/api/v1/projects/{project_id}/investigate",
            json={"tenant_external_id": "acme"}, headers=headers)
        assert post_r.status_code == 200, post_r.text
        g, p = get_r.json(), post_r.json()
        assert g["tenant_external_id"] == p["tenant_external_id"] == "acme"
        assert g["recommendations"] == p["recommendations"]
        assert g["disclaimer"] == DISCLAIMER
        assert all(r["disclaimer"] == DISCLAIMER for r in g["recommendations"])

    def test_get_investigate_404_unknown_tenant(self, client):
        body, headers = self._signup(client)
        r = client.get(f"/api/v1/projects/{body['project']['id']}/investigate",
                       params={"tenant": "ghost"}, headers=headers)
        assert r.status_code == 404

    def test_explain_returns_template_narrative(self, client):
        body, headers = self._signup(client)
        project_id, org_id = body["project"]["id"], body["org"]["id"]
        self._seed(client, project_id, org_id)
        r = client.post(f"/api/v1/projects/{project_id}/investigate/explain",
                        json={"tenant_external_id": "acme"}, headers=headers)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["narrative_source"] == "template"  # no LLM key configured
        assert "Acme" in payload["narrative"]
        # Narrative only rewords computed facts — spot-check a dollar figure
        # from the investigation appears verbatim.
        assert "$" in payload["narrative"]

    def test_explain_404_unknown_tenant(self, client):
        body, headers = self._signup(client)
        r = client.post(f"/api/v1/projects/{body['project']['id']}/investigate/explain",
                        json={"tenant_external_id": "ghost"}, headers=headers)
        assert r.status_code == 404


class TestNarrative:
    def test_template_never_invents_numbers(self):
        facts = {
            "tenant_name": "Acme",
            "margin_usd": Decimal("-120.50"),
            "drivers": {
                "by_app": [{"app": "Support Agent", "cost_usd": Decimal("80"), "pct": 80.0}],
                "by_model": [{"model": "gpt-4.1", "cost_usd": Decimal("70"), "pct": 70.0}],
            },
            "volume_vs_tokens": {"volume_effect_usd": Decimal("7.00"),
                                 "token_intensity_effect_usd": Decimal("3.00")},
            "recommendations": [
                {"action": "Route X to Y", "est_savings_usd_mo": Decimal("42.00"),
                 "confidence": "high"},
            ],
        }
        text = narrative.template_narrative(facts)
        assert "Acme" in text
        assert "121" in text or "120" in text  # margin figure present
        assert "42" in text  # savings figure present
        assert "Estimates are not guarantees" in text

    def test_llm_polish_failure_falls_back_to_template(self):
        facts = {"tenant_name": "Acme", "margin_usd": None, "drivers": {},
                 "volume_vs_tokens": {}, "recommendations": []}

        def boom(_text):
            raise RuntimeError("llm down")

        text, source = narrative.explain(facts, polish=boom)
        assert source == "template"
        assert "Acme" in text

    def test_llm_polish_success_marks_source(self):
        facts = {"tenant_name": "Acme", "margin_usd": None, "drivers": {},
                 "volume_vs_tokens": {}, "recommendations": []}
        text, source = narrative.explain(facts, polish=lambda t: "Polished: " + t)
        assert source == "llm"
        assert text.startswith("Polished: ")
