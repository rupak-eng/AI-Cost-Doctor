"""Phase 3 tests: project API keys, event ingest, CSV upload, project P&L /
investigate — all against the local Postgres test DB (with migrations).

Round-trip proof: the customer endpoints' HTTP responses are asserted
field-for-field against the shared services (compute_pnl /
investigate_tenant), and the demo endpoints are asserted to literally call
the same service functions — demo and live paths share the engine.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as m
import app.api.v1.endpoints.demo as demo_module
from app.api.v1 import deps
from app.schemas import demo as demo_schemas
from app.schemas import projects as project_schemas
from app.services import costing
from app.services import pnl as pnl_service
from app.services.costing import ensure_catalog_in_db, load_catalog
from app.services.investigate import investigate_tenant
from app.services.seed_demo import demo_org_id, demo_project_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _signup(client, org_name="P3 Org"):
    email = f"p3-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/api/v1/auth/signup", json={
        "email": email, "password": "correct-horse-9", "org_name": org_name})
    assert r.status_code == 201, r.text
    body = r.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return body, headers


def _authed(client):
    """(body, headers, project_id, org_id)."""
    body, headers = _signup(client)
    return body, headers, body["project"]["id"], body["org"]["id"]


def _freeze_service_time(monkeypatch):
    """Pin datetime.now() inside the analytics services.

    The demo seed writes events up to ~1h in the future and the P&L /
    investigate windows end at "now", so two computations seconds apart can
    legitimately disagree (verified: 3s apart moved cust-a's cost). Freezing
    "now" makes the HTTP-vs-service comparison deterministic without
    touching the seed data or the services under test.
    """
    fixed = datetime.now(timezone.utc)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr(pnl_service, "datetime", _FrozenDateTime)
    import app.services.investigate as investigate_service
    monkeypatch.setattr(investigate_service, "datetime", _FrozenDateTime)


def _make_key(client, headers, project_id, name="ci-key"):
    r = client.post(f"/api/v1/projects/{project_id}/api-keys",
                    json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _event(*, tenant="acme", provider="openai", model="gpt-4.1",
           in_tok=1000, out_tok=500, app="Support Agent", minutes_ago=60 * 24 * 3,
           **kw):
    ev = {
        "occurred_at": (_now() - timedelta(minutes=minutes_ago)).isoformat(),
        "provider": provider,
        "model": model,
        "application": app,
        "tenant_id": tenant,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }
    ev.update(kw)
    return ev


def _expected_cost(ev: dict) -> Decimal:
    catalog = costing.load_catalog()
    price = costing.price_for(
        catalog, provider=ev["provider"], model=ev["model"],
        at=datetime.fromisoformat(ev["occurred_at"]))
    return costing.event_cost(
        input_tokens=ev["input_tokens"], output_tokens=ev["output_tokens"],
        price=price,
        cached_input_tokens=ev.get("cached_input_tokens", 0),
        reasoning_tokens=ev.get("reasoning_tokens", 0))


def _rls(db, org_id):
    deps.set_rls_org(db, uuid.UUID(str(org_id)))


@pytest.fixture(scope="module", autouse=True)
def catalog_seeded(db_url):
    """Ensure the pricing catalog is in model_prices.

    Migration 001 seeds it on Postgres; the SQLite fallback creates an empty
    schema, so seed it here (idempotent — a no-op when already present).
    """
    engine = create_engine(db_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        ensure_catalog_in_db(session, load_catalog())
        session.commit()
    finally:
        session.close()
        engine.dispose()


@contextmanager
def _write_session(db_url):
    """A dedicated session for test setup writes (commits for real).

    The function-scoped `db` fixture wraps everything in a rollback-only
    transaction, so writes that HTTP requests must see go through here.
    """
    engine = create_engine(db_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _set_revenue(db_url, org_id, project_id, external_id, amount: Decimal):
    with _write_session(db_url) as s:
        _rls(s, org_id)
        t = s.query(m.Tenant).filter_by(
            org_id=uuid.UUID(str(org_id)), project_id=uuid.UUID(str(project_id)),
            external_id=external_id).one()
        t.monthly_revenue_usd = amount


# ---------------------------------------------------------------------------
# Project API keys
# ---------------------------------------------------------------------------

class TestApiKeys:
    def test_create_shows_secret_once_and_hashes_at_rest(self, client, db):
        _, headers, project_id, org_id = _authed(client)
        created = _make_key(client, headers, project_id, name="prod-ingest")

        secret = created["api_key"]
        assert len(secret) == 48, created
        assert created["key_prefix"] == secret[:8]
        assert created["name"] == "prod-ingest"
        assert created["created_at"]

        # Listing never exposes the secret.
        r = client.get(f"/api/v1/projects/{project_id}/api-keys", headers=headers)
        assert r.status_code == 200, r.text
        listed = r.json()
        assert len(listed) == 1
        assert "api_key" not in listed[0]
        assert listed[0]["key_prefix"] == secret[:8]
        assert listed[0]["revoked_at"] is None

        # At rest: only the SHA-256 digest, never the plaintext.
        _rls(db, org_id)
        row = db.query(m.ApiKey).filter_by(id=uuid.UUID(created["id"])).one()
        assert row.key_hash == hashlib.sha256(secret.encode()).hexdigest()
        assert row.key_hash != secret
        assert len(row.key_hash) == 64

    def test_revoke_then_ingest_401(self, client):
        _, headers, project_id, _ = _authed(client)
        created = _make_key(client, headers, project_id)

        r = client.delete(
            f"/api/v1/projects/{project_id}/api-keys/{created['id']}", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["revoked_at"] is not None

        r = client.post("/api/v1/ingest/events",
                        json={"events": [_event()]},
                        headers={"X-API-Key": created["api_key"]})
        assert r.status_code == 401, r.text

    def test_cross_org_project_access_404(self, client):
        _, headers_a, project_a, _ = _authed(client)
        _, headers_b, _, _ = _authed(client)

        for method, url, kwargs in [
            ("get", f"/api/v1/projects/{project_a}/api-keys", {}),
            ("post", f"/api/v1/projects/{project_a}/api-keys", {"json": {"name": "x"}}),
            ("get", f"/api/v1/projects/{project_a}/pnl", {}),
            ("post", f"/api/v1/projects/{project_a}/investigate",
             {"json": {"tenant_external_id": "nope"}}),
        ]:
            r = client.request(method, url, headers=headers_b, **kwargs)
            assert r.status_code == 404, (method, url, r.text)

    def test_unknown_project_404(self, client):
        _, headers, _, _ = _authed(client)
        bogus = str(uuid.uuid4())
        r = client.get(f"/api/v1/projects/{bogus}/api-keys", headers=headers)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Event ingest
# ---------------------------------------------------------------------------

class TestIngest:
    def test_ingest_round_trip(self, client, db):
        _, headers, project_id, org_id = _authed(client)
        created = _make_key(client, headers, project_id)

        events = [
            _event(tenant="acme", in_tok=10_000, out_tok=2_000, minutes_ago=100),
            _event(tenant="acme", provider="anthropic",
                   model="claude-3-5-haiku-20241022", in_tok=5_000, out_tok=1_000,
                   cost_reported_usd="0.0123", minutes_ago=200),
            _event(tenant="globex", model="gpt-99-nonexistent", in_tok=100, out_tok=100,
                   minutes_ago=300),
        ]
        r = client.post("/api/v1/ingest/events", json={"events": events},
                        headers={"X-API-Key": created["api_key"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ingested"] == 3
        assert body["unpriced"] == 1
        expected_total = _expected_cost(events[0]) + _expected_cost(events[1])
        # Money serializes as decimal strings over HTTP — compare exactly.
        assert Decimal(str(body["total_calculated_usd"])) == expected_total, body

        # Stored rows carry the deterministic calculated costs.
        _rls(db, org_id)
        rows = (db.query(m.UsageEvent)
                .filter_by(project_id=uuid.UUID(project_id)).all())
        assert len(rows) == 3
        assert all(r.source == "event_api" for r in rows)
        by_model = {r.model: r for r in rows}
        assert by_model["gpt-4.1"].cost_calculated_usd == _expected_cost(events[0])
        assert by_model["claude-3-5-haiku-20241022"].cost_reported_usd == Decimal("0.0123")
        unpriced = by_model["gpt-99-nonexistent"]
        assert unpriced.cost_calculated_usd is None

        # Tenants auto-created: name = external_id, revenue NULL.
        tenants = {t.external_id: t for t in
                   db.query(m.Tenant).filter_by(project_id=uuid.UUID(project_id)).all()}
        assert set(tenants) == {"acme", "globex"}
        assert tenants["acme"].name == "acme"
        assert tenants["acme"].monthly_revenue_usd is None

    def test_ingest_rejects_bad_keys(self, client):
        r = client.post("/api/v1/ingest/events", json={"events": [_event()]},
                        headers={"X-API-Key": "bogus-key"})
        assert r.status_code == 401
        r = client.post("/api/v1/ingest/events", json={"events": [_event()]})
        assert r.status_code == 401

    def test_ingest_validation_422(self, client):
        _, headers, project_id, _ = _authed(client)
        key = _make_key(client, headers, project_id)["api_key"]
        h = {"X-API-Key": key}
        bad = _event(); bad["input_tokens"] = -1
        assert client.post("/api/v1/ingest/events", json={"events": [bad]}, headers=h).status_code == 422
        bad = _event(); bad["occurred_at"] = "not-a-time"
        assert client.post("/api/v1/ingest/events", json={"events": [bad]}, headers=h).status_code == 422
        bad = _event(); del bad["model"]
        assert client.post("/api/v1/ingest/events", json={"events": [bad]}, headers=h).status_code == 422
        assert client.post("/api/v1/ingest/events", json={"events": []}, headers=h).status_code == 422


# ---------------------------------------------------------------------------
# Project P&L + investigate — HTTP responses must equal the shared services
# ---------------------------------------------------------------------------

def _seed_p3_data(client, headers, project_id, key):
    """Ingest two tenants: 'big' (spend > revenue → margin_killer) and
    'small' (no revenue → unknown). Revenue for 'big' is set directly."""
    events = (
        [_event(tenant="big", in_tok=500_000, out_tok=100_000, minutes_ago=60 * 24 * d)
         for d in range(1, 6)]
        + [_event(tenant="small", in_tok=1_000, out_tok=200, minutes_ago=60 * 24 * 2)]
    )
    r = client.post("/api/v1/ingest/events", json={"events": events},
                    headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    return events


class TestProjectPnlInvestigate:
    def test_demo_module_uses_shared_services(self):
        # The proof that demo and live paths share the engine: the demo
        # endpoint module references the very same service functions.
        assert demo_module.compute_pnl is pnl_service.compute_pnl
        assert demo_module.investigate_tenant is investigate_tenant

    def test_pnl_matches_service(self, client, db, db_url):
        _, headers, project_id, org_id = _authed(client)
        key = _make_key(client, headers, project_id)["api_key"]
        _seed_p3_data(client, headers, project_id, key)
        _set_revenue(db_url, org_id, project_id, "big", Decimal("5.00"))

        r = client.get(f"/api/v1/projects/{project_id}/pnl", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["data_label"] == "customer"

        # Serialize the service output through the same response model the
        # endpoint uses, then compare structurally — exact, no float haze.
        _rls(db, org_id)
        rows = pnl_service.compute_pnl(db, uuid.UUID(org_id), uuid.UUID(project_id))
        expected = project_schemas.ProjectPnLResponse(
            tenants=[project_schemas.ProjectPnLRow(**r) for r in rows]
        ).model_dump(mode="json")["tenants"]
        got = {t["tenant_external_id"]: t for t in body["tenants"]}
        exp = {t["tenant_external_id"]: t for t in expected}
        assert set(got) == set(exp) == {"big", "small"}
        for ext, exp_row in exp.items():
            assert got[ext] == exp_row, ext

        assert got["big"]["status"] == "margin_killer"
        assert Decimal(got["big"]["revenue_usd"]) == Decimal("5.00")
        assert Decimal(got["big"]["margin_usd"]) < 0
        assert got["small"]["status"] == "unknown"
        assert got["small"]["revenue_usd"] is None
        assert got["small"]["margin_usd"] is None

    def test_investigate_matches_service(self, client, db, db_url):
        _, headers, project_id, org_id = _authed(client)
        key = _make_key(client, headers, project_id)["api_key"]
        _seed_p3_data(client, headers, project_id, key)
        _set_revenue(db_url, org_id, project_id, "big", Decimal("5.00"))

        r = client.post(f"/api/v1/projects/{project_id}/investigate",
                        json={"tenant_external_id": "big"}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["data_label"] == "customer"

        _rls(db, org_id)
        result = investigate_tenant(db, uuid.UUID(org_id), uuid.UUID(project_id), "big")
        expected = project_schemas.ProjectInvestigateResponse(
            **result).model_dump(mode="json")
        assert body == expected

        r = client.post(f"/api/v1/projects/{project_id}/investigate",
                        json={"tenant_external_id": "nope"}, headers=headers)
        assert r.status_code == 404

    def test_demo_http_matches_shared_service(self, client, db, monkeypatch):
        """End-to-end proof on the seeded demo dataset: /demo/* HTTP responses
        equal the shared services' output (plus the demo label)."""
        r = client.post("/api/v1/demo/seed")
        assert r.status_code in (201, 409), r.text
        if r.status_code == 409:
            assert client.delete("/api/v1/demo/reset").status_code == 200
            assert client.post("/api/v1/demo/seed").status_code == 201
        _freeze_service_time(monkeypatch)
        try:
            _rls(db, demo_org_id())
            expected_pnl = demo_schemas.PnLResponse(
                tenants=[demo_schemas.PnLRow(**r) for r in
                         pnl_service.compute_pnl(db, demo_org_id(), demo_project_id())]
            ).model_dump(mode="json")
            body = client.get("/api/v1/demo/pnl").json()
            assert body == expected_pnl

            _rls(db, demo_org_id())
            expected_inv = demo_schemas.InvestigateResponse(
                **investigate_tenant(db, demo_org_id(), demo_project_id(), "cust-a")
            ).model_dump(mode="json")
            body = client.post("/api/v1/demo/investigate",
                               json={"tenant_external_id": "cust-a"}).json()
            assert body == expected_inv
        finally:
            assert client.delete("/api/v1/demo/reset").status_code == 200


# ---------------------------------------------------------------------------
# CSV upload
# ---------------------------------------------------------------------------

_CSV = """ts,prov,model,app,tenant,in_tok,out_tok,cost
2026-09-10T10:00:00Z,openai,gpt-4.1,Support Agent,t1,10000,2000,
2026-09-11T11:00:00Z,openai,gpt-4.1-mini,Support Agent,t1,5000,1000,0.0042
2026-09-12T12:00:00Z,anthropic,claude-3-5-haiku-20241022,Classifier,t2,3000,500,
2026-09-13T13:00:00Z,openai,gpt-4.1,Support Agent,t2,1000,200,
not-a-time,openai,gpt-4.1,Support Agent,t3,100,100,
2026-09-14T14:00:00Z,openai,gpt-4.1,Support Agent,t3,-5,100,
"""

_COLUMN_MAP = {
    "timestamp": "ts", "provider": "prov", "model": "model",
    "application": "app", "tenant": "tenant",
    "input_tokens": "in_tok", "output_tokens": "out_tok",
    "cost_reported": "cost",
}


def _upload(client, headers, project_id, *, dry_run="true", revenues=None,
            csv_text=_CSV, column_map=_COLUMN_MAP):
    data = {"project_id": project_id, "column_map": json.dumps(column_map),
            "dry_run": dry_run}
    if revenues is not None:
        data["revenues"] = json.dumps(revenues)
    return client.post("/api/v1/integrations/csv/upload",
                       files={"file": ("events.csv", csv_text, "text/csv")},
                       data=data, headers=headers)


def _row_cost(provider, model, at, in_tok, out_tok):
    catalog = costing.load_catalog()
    price = costing.price_for(catalog, provider=provider, model=model, at=at)
    return costing.event_cost(input_tokens=in_tok, output_tokens=out_tok, price=price)


class TestCsvUpload:
    def test_dry_run_preview_then_commit(self, client, db):
        _, headers, project_id, org_id = _authed(client)

        r = _upload(client, headers, project_id, dry_run="true")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows_parsed"] == 6
        assert body["rows_valid"] == 4
        assert body["rows_invalid"] == 2
        assert body["committed"] == 0
        reasons = [i["reason"] for i in body["invalid_sample"]]
        assert any("timestamp" in x for x in reasons)
        assert any("negative" in x for x in reasons)
        assert {i["row"] for i in body["invalid_sample"]} == {6, 7}

        # Preview math matches the deterministic cost engine exactly.
        assert len(body["preview"]) == 4
        p0 = body["preview"][0]
        assert p0["tenant"] == "t1" and p0["model"] == "gpt-4.1"
        assert Decimal(str(p0["cost_calculated_usd"])) == _row_cost(
            "openai", "gpt-4.1", datetime(2026, 9, 10, 10, tzinfo=timezone.utc),
            10_000, 2_000)
        assert p0["cost_reported_usd"] is None
        assert Decimal(str(body["preview"][1]["cost_reported_usd"])) == Decimal("0.0042")
        assert all(p["cost_calculated_usd"] is not None for p in body["preview"])

        # Dry run wrote nothing.
        _rls(db, org_id)
        assert db.query(m.UsageEvent).filter_by(
            project_id=uuid.UUID(project_id)).count() == 0

        # Commit: events + tenants + revenues.
        r = _upload(client, headers, project_id, dry_run="false",
                    revenues={"t1": "500.00", "t3": "100"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["committed"] == 4
        assert body["rows_valid"] == 4

        _rls(db, org_id)
        assert db.query(m.UsageEvent).filter_by(
            project_id=uuid.UUID(project_id), source="csv").count() == 4
        tenants = {t.external_id: t for t in db.query(m.Tenant).filter_by(
            project_id=uuid.UUID(project_id)).all()}
        assert set(tenants) == {"t1", "t2", "t3"}  # t3 from revenues map
        assert tenants["t1"].monthly_revenue_usd == Decimal("500.00")
        assert tenants["t2"].monthly_revenue_usd is None
        assert tenants["t1"].name == "t1"

        # The committed data flows into the project P&L.
        r = client.get(f"/api/v1/projects/{project_id}/pnl", headers=headers)
        assert r.status_code == 200, r.text
        by_ext = {t["tenant_external_id"]: t for t in r.json()["tenants"]}
        assert Decimal(by_ext["t1"]["revenue_usd"]) == Decimal("500.00")
        assert by_ext["t1"]["status"] in ("margin_killer", "at_risk", "healthy")
        assert by_ext["t2"]["status"] == "unknown"

    def test_unpriced_csv_row(self, client):
        _, headers, project_id, _ = _authed(client)
        csv_text = ("ts,prov,model,in_tok,out_tok\n"
                    "2026-09-10T10:00:00Z,openai,gpt-99,100,100\n")
        cmap = {"timestamp": "ts", "provider": "prov", "model": "model",
                "input_tokens": "in_tok", "output_tokens": "out_tok"}
        r = _upload(client, headers, project_id, dry_run="true",
                    csv_text=csv_text, column_map=cmap)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows_valid"] == 1 and body["rows_invalid"] == 0
        assert body["preview"][0]["cost_calculated_usd"] is None
        assert "unpriced" in body["preview"][0]["note"]

    def test_bad_inputs_400(self, client):
        _, headers, project_id, _ = _authed(client)
        # Missing required canonical field in the map.
        bad_map = {k: v for k, v in _COLUMN_MAP.items() if k != "model"}
        r = _upload(client, headers, project_id, column_map=bad_map)
        assert r.status_code == 400, r.text
        # Mapped header absent from the CSV.
        bad_map = dict(_COLUMN_MAP); bad_map["model"] = "nope"
        r = _upload(client, headers, project_id, column_map=bad_map)
        assert r.status_code == 400, r.text
        # Malformed revenues.
        r = _upload(client, headers, project_id, revenues={"t1": "abc"})
        assert r.status_code == 400, r.text
        # Cross-org project.
        _, headers_b, _, _ = _authed(client)
        r = _upload(client, headers_b, project_id)
        assert r.status_code == 404, r.text

    def test_csv_minimal_columns(self, client, db):
        """Only the 5 required canonical fields — optionals stay NULL."""
        _, headers, project_id, org_id = _authed(client)
        csv_text = ("when,who,what,i,o\n"
                    "2026-09-10T10:00:00Z,openai,gpt-4.1,1000,500\n")
        cmap = {"timestamp": "when", "provider": "who", "model": "what",
                "input_tokens": "i", "output_tokens": "o"}
        r = _upload(client, headers, project_id, dry_run="false",
                    csv_text=csv_text, column_map=cmap)
        assert r.status_code == 200, r.text
        assert r.json()["committed"] == 1
        _rls(db, org_id)
        ev = db.query(m.UsageEvent).filter_by(
            project_id=uuid.UUID(project_id)).one()
        assert ev.application is None and ev.tenant_id is None
        assert ev.cost_calculated_usd is not None
