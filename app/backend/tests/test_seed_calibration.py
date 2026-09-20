"""Seed calibration: the engine-computed P&L over seeded events must land
within ±5% of the calibration targets. No P&L figure is hardcoded in the
seed — everything flows through costing.py.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from app import models as m
from app.services import recommend, seed_demo
from app.services.seed_demo import demo_org_id


def _rls(session):
    """Pin the RLS org context for direct-DB test queries (PG only)."""
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SET LOCAL app.org_id = :oid"),
                        {"oid": str(demo_org_id())})


def _pct_within(actual: Decimal, target: Decimal, pct: float = 5.0) -> bool:
    # Symmetric band around the target; works for negative targets too
    # (margin can be negative). Margin is revenue - cost, so a small cost
    # miss amplifies in margin terms — the band is on the margin itself.
    return abs(actual - target) <= abs(target) * Decimal(pct) / Decimal(100)


@pytest.fixture(scope="module")
def seeded(db_url):
    # Depends on db_url so the schema is freshly migrated before seeding.
    engine = create_engine(__import__("os").environ["DATABASE_URL"])
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        seed_demo.seed_demo_org(session)
    except ValueError:
        seed_demo.reset_demo_org(session)
        seed_demo.seed_demo_org(session)
    yield session
    try:
        seed_demo.reset_demo_org(session)
    finally:
        session.close()
        engine.dispose()


def _pnl(session):
    _rls(session)
    org_id = demo_org_id()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)
    cost_rows = (
        session.query(m.UsageEvent.tenant_id, func.sum(m.UsageEvent.cost_calculated_usd))
        .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.occurred_at >= start)
        .group_by(m.UsageEvent.tenant_id).all()
    )
    costs = {ext: (total or Decimal(0)) for ext, total in cost_rows}
    tenants = session.query(m.Tenant).filter_by(org_id=org_id).all()
    out = {}
    for t in tenants:
        cost = costs.get(t.external_id, Decimal(0))
        revenue = t.monthly_revenue_usd or Decimal(0)
        out[t.external_id] = {
            "name": t.name, "revenue": revenue, "cost": cost, "margin": revenue - cost,
        }
    return out


class TestCalibration:
    # Cost (the engine-driven quantity) is asserted at ±5%. Margin is
    # revenue - cost, so it gets a ±10% band: for thin-margin tenants a 1%
    # cost deviation amplifies to ~13% in margin terms (C: 741/58), and
    # over-constraining it would mean overfitting the deterministic RNG
    # stream rather than testing the economics.
    def test_customer_a_margin_killer(self, seeded):
        pnl = _pnl(seeded)["cust-a"]
        assert pnl["revenue"] == Decimal("499")
        assert _pct_within(pnl["cost"], Decimal("681")), f"cost={pnl['cost']}"
        assert _pct_within(pnl["margin"], Decimal("-182"), pct=10.0), f"margin={pnl['margin']}"
        assert pnl["margin"] < 0

    def test_customer_b_healthy(self, seeded):
        pnl = _pnl(seeded)["cust-b"]
        assert pnl["revenue"] == Decimal("299")
        assert _pct_within(pnl["cost"], Decimal("247")), f"cost={pnl['cost']}"
        assert _pct_within(pnl["margin"], Decimal("52"), pct=10.0), f"margin={pnl['margin']}"
        assert pnl["margin"] >= Decimal("0.15") * pnl["revenue"]  # healthy per binding rule

    def test_customer_c(self, seeded):
        pnl = _pnl(seeded)["cust-c"]
        assert pnl["revenue"] == Decimal("799")
        assert _pct_within(pnl["cost"], Decimal("741")), f"cost={pnl['cost']}"
        assert _pct_within(pnl["margin"], Decimal("58"), pct=10.0), f"margin={pnl['margin']}"
        # Binding status rule: margin < 15% of revenue -> at_risk
        # ($58 < 0.15 x $799). Documented deviation from the draft "healthy".
        assert pnl["margin"] < Decimal("0.15") * pnl["revenue"]
        assert pnl["margin"] > 0

    def test_gpt41_share_of_support_agent(self, seeded):
        """~81% of Support Agent cost from gpt-4.1 (draft-recipe check value)."""
        _rls(seeded)
        org_id = demo_org_id()
        now = datetime.now(timezone.utc)
        rows = (
            seeded.query(m.UsageEvent.model, func.sum(m.UsageEvent.cost_calculated_usd))
            .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.tenant_id == "cust-a",
                    m.UsageEvent.application == "Support Agent",
                    m.UsageEvent.occurred_at >= now - timedelta(days=30))
            .group_by(m.UsageEvent.model).all()
        )
        by_model = {model: total for model, total in rows}
        total = sum(by_model.values(), Decimal(0))
        share = by_model["gpt-4.1"] / total
        assert Decimal("0.76") <= share <= Decimal("0.86"), f"share={share}"

    def test_routing_savings_figure(self, seeded):
        """The shared recommend.py engine must find ~$140/mo on Customer A."""
        _rls(seeded)
        org_id = demo_org_id()
        now = datetime.now(timezone.utc)
        rows = (
            seeded.query(
                m.UsageEvent.application, m.UsageEvent.provider, m.UsageEvent.model,
                func.count(m.UsageEvent.id),
                func.sum(m.UsageEvent.cost_calculated_usd),
                func.sum(m.UsageEvent.input_tokens),
                func.sum(m.UsageEvent.output_tokens),
            )
            .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.tenant_id == "cust-a",
                    m.UsageEvent.occurred_at >= now - timedelta(days=30))
            .group_by(m.UsageEvent.application, m.UsageEvent.provider, m.UsageEvent.model)
            .all()
        )
        pairs = [recommend.PairStats(
            application=a, provider=p, model=mo, requests=n,
            input_tokens=int(i or 0), output_tokens=int(o or 0), cost_usd=c or Decimal(0))
            for a, p, mo, n, c, i, o in rows]
        opps = recommend.model_routing_opportunity(pairs)
        assert opps, "expected at least one routing opportunity for Customer A"
        top = opps[0]
        assert top.application == "Classification"
        assert top.from_model == "gpt-4.1" and top.to_model == "gpt-4.1-mini"
        assert _pct_within(top.est_savings_usd_mo, Decimal("140")), \
            f"savings={top.est_savings_usd_mo}"
        assert top.confidence == "medium"

    def test_seed_is_deterministic(self, seeded):
        """Re-seeding after reset yields the same tenant totals (seeded RNG)."""
        before = {k: v["cost"] for k, v in _pnl(seeded).items()}
        seed_demo.reset_demo_org(seeded)
        seed_demo.seed_demo_org(seeded)
        after = {k: v["cost"] for k, v in _pnl(seeded).items()}
        assert before.keys() == after.keys()
        for k in before:
            assert abs(before[k] - after[k]) / before[k] < Decimal("0.02"), \
                f"{k}: {before[k]} vs {after[k]}"
