"""Demo API tests: response shapes, data_label, calibration via HTTP."""
from decimal import Decimal

import pytest


def _pct_within(actual, target, pct=5.0):
    # Symmetric band; safe for negative targets (margins can be negative).
    actual, target = Decimal(str(actual)), Decimal(str(target))
    return abs(actual - target) <= abs(target) * Decimal(str(pct)) / Decimal(100)


@pytest.fixture(scope="module")
def demo_client(db_url):
    """Module-scoped: seed once via HTTP, exercise endpoints, reset at teardown.

    Builds its own TestClient (module scope) instead of reusing the
    function-scoped `client` fixture — avoids a pytest ScopeMismatch.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.core.db import get_db

    engine = create_engine(db_url)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    try:
        r = client.post("/api/v1/demo/seed")
        assert r.status_code in (201, 409), r.text
        if r.status_code == 409:
            client.delete("/api/v1/demo/reset")
            r = client.post("/api/v1/demo/seed")
            assert r.status_code == 201, r.text
        yield client
    finally:
        client.delete("/api/v1/demo/reset")
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()


class TestDemoPnl:
    def test_shape_and_label(self, demo_client):
        r = demo_client.get("/api/v1/demo/pnl")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["data_label"] == "demo"
        assert len(body["tenants"]) == 3
        for t in body["tenants"]:
            for field in ("tenant_id", "tenant_external_id", "name", "revenue_usd",
                          "ai_cost_usd", "margin_usd", "status"):
                assert field in t, f"missing {field}"
            assert t["status"] in ("margin_killer", "at_risk", "healthy")

    def test_calibration_via_api(self, demo_client):
        body = demo_client.get("/api/v1/demo/pnl").json()
        by_ext = {t["tenant_external_id"]: t for t in body["tenants"]}
        a, b, c = by_ext["cust-a"], by_ext["cust-b"], by_ext["cust-c"]
        assert a["status"] == "margin_killer"
        assert _pct_within(a["ai_cost_usd"], 681), a
        assert _pct_within(a["margin_usd"], -182, pct=10.0), a
        assert b["status"] == "healthy"
        assert _pct_within(b["ai_cost_usd"], 247), b
        assert _pct_within(b["margin_usd"], 52, pct=10.0), b
        # Binding status rule puts C at_risk (margin < 15% of revenue).
        assert c["status"] == "at_risk"
        assert _pct_within(c["ai_cost_usd"], 741), c
        assert _pct_within(c["margin_usd"], 58, pct=10.0), c


class TestDemoInvestigate:
    def test_shape_and_label(self, demo_client):
        r = demo_client.post("/api/v1/demo/investigate",
                             json={"tenant_external_id": "cust-a"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["data_label"] == "demo"
        assert body["tenant_external_id"] == "cust-a"
        assert isinstance(body["summary"], str) and len(body["summary"]) > 50
        assert "by_model" in body["drivers"] and "by_app" in body["drivers"]
        for d in body["drivers"]["by_model"]:
            assert {"model", "cost_usd", "pct"} <= set(d)
        for d in body["drivers"]["by_app"]:
            assert {"app", "cost_usd", "pct"} <= set(d)
        vvt = body["volume_vs_tokens"]
        assert {"requests_delta_pct", "avg_tokens_per_request_delta_pct"} <= set(vvt)
        assert len(body["expensive_workflows"]) > 0
        wf = body["expensive_workflows"][0]
        assert {"app", "model", "requests", "cost_usd", "cost_per_request_usd"} <= set(wf)
        rec = body["recommendation"]
        assert rec is not None
        assert {"action", "est_savings_usd_mo", "confidence", "post_change_margin_usd"} <= set(rec)
        assert rec["confidence"] in ("high", "medium", "low")

    def test_recommendation_numbers(self, demo_client):
        pnl = {t["tenant_external_id"]: t
               for t in demo_client.get("/api/v1/demo/pnl").json()["tenants"]}
        body = demo_client.post("/api/v1/demo/investigate",
                                json={"tenant_external_id": "cust-a"}).json()
        rec = body["recommendation"]
        assert _pct_within(rec["est_savings_usd_mo"], 140), rec
        assert rec["confidence"] == "high"  # 64.8k requests > 1k
        # Post-change margin = current margin + estimated savings (an estimate,
        # never a guarantee). Assert the relationship, not a hardcoded number.
        margin = Decimal(str(pnl["cust-a"]["margin_usd"]))
        savings = Decimal(str(rec["est_savings_usd_mo"]))
        post = Decimal(str(rec["post_change_margin_usd"]))
        assert abs(post - (margin + savings)) < Decimal("1"), rec
        assert "classification" in rec["action"].lower()

    def test_summary_shape(self, demo_client):
        body = demo_client.post("/api/v1/demo/investigate",
                                json={"tenant_external_id": "cust-a"}).json()
        s = body["summary"]
        # Template shape with computed facts (money figures asserted loosely).
        assert "negative AI margin" in s
        assert "of their AI cost comes from the" in s
        assert "spend." in s
        assert "could potentially reduce AI cost by" in s
        assert "Estimated post-change margin" in s
        assert "Confidence: High" in s  # 64.8k requests > 1k

    def test_volume_growth_detected(self, demo_client):
        body = demo_client.post("/api/v1/demo/investigate",
                                json={"tenant_external_id": "cust-a"}).json()
        vvt = body["volume_vs_tokens"]
        # Customer A has deterministic growth in the last 7 days: request
        # volume rises while tokens/request stay ~flat.
        assert vvt["requests_delta_pct"] > 5, vvt
        assert abs(vvt["avg_tokens_per_request_delta_pct"]) < 10, vvt

    def test_unknown_tenant_404(self, demo_client):
        r = demo_client.post("/api/v1/demo/investigate",
                             json={"tenant_external_id": "nope"})
        assert r.status_code == 404

    def test_healthy_tenant_investigate(self, demo_client):
        r = demo_client.post("/api/v1/demo/investigate",
                             json={"tenant_external_id": "cust-b"})
        assert r.status_code == 200
        body = r.json()
        assert body["data_label"] == "demo"
        assert "positive AI margin" in body["summary"]


class TestDemoSeedReset:
    def test_seed_is_idempotent_guarded(self, demo_client):
        r = demo_client.post("/api/v1/demo/seed")
        assert r.status_code == 409

    def test_reset_then_pnl_404(self, client):
        # Separate client usage: seed, reset, then pnl must 404.
        r = client.post("/api/v1/demo/seed")
        assert r.status_code in (201, 409)
        if r.status_code == 409:
            client.delete("/api/v1/demo/reset")
            assert client.post("/api/v1/demo/seed").status_code == 201
        assert client.delete("/api/v1/demo/reset").status_code == 200
        assert client.get("/api/v1/demo/pnl").status_code == 404
        # Re-seed for the module fixture's teardown symmetry (harmless if 409).
        client.post("/api/v1/demo/seed")
