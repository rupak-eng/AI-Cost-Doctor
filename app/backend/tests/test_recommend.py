"""Unit tests for the recommendation engine (no DB required)."""
from datetime import date
from decimal import Decimal

from app.services.costing import Price, load_catalog
from app.services.recommend import PairStats, model_routing_opportunity


def _catalog():
    return load_catalog()


def _pair(**kw):
    base = dict(application="Classification", provider="openai", model="gpt-4.1",
                requests=64_815, input_tokens=64_815 * 1500, output_tokens=64_815 * 300,
                cost_usd=Decimal("350"))
    base.update(kw)
    return PairStats(**base)


class TestModelRouting:
    def test_savings_math_matches_rule(self):
        # Classification on gpt-4.1 ($2/$8) vs mini ($0.4/$1.6):
        # full delta = 0.8 x 350 = 280; x 50% share = $140.
        opps = model_routing_opportunity([_pair()], _catalog())
        assert len(opps) == 1
        opp = opps[0]
        assert opp.to_model == "gpt-4.1-mini"
        assert opp.est_savings_usd_mo == Decimal("140.00")
        assert opp.confidence == "medium"  # 64.8k requests > 10k

    def test_shiftable_share_is_applied(self):
        opps = model_routing_opportunity([_pair()], _catalog(), shiftable_share=Decimal("1.0"))
        assert opps[0].est_savings_usd_mo == Decimal("280.00")

    def test_below_threshold_pair_ignored(self):
        # 9000 x $0.0054 = $48.60/mo < $50 threshold -> ignored.
        pair = _pair(requests=9000, input_tokens=9000 * 1500, output_tokens=9000 * 300,
                     cost_usd=Decimal("48.60"))
        assert model_routing_opportunity([pair], _catalog()) == []

    def test_at_threshold_pair_included(self):
        # 10000 x $0.0054 = $54.00/mo >= $50 threshold -> included.
        pair = _pair(requests=10000, input_tokens=10000 * 1500, output_tokens=10000 * 300,
                     cost_usd=Decimal("54.00"))
        assert len(model_routing_opportunity([pair], _catalog())) == 1

    def test_no_cheaper_same_provider_model(self):
        # gpt-4.1-mini is already the cheapest OpenAI model in the catalog.
        pair = _pair(application="Doc Q&A", model="gpt-4.1-mini", requests=44_107,
                     input_tokens=44_107 * 6000, output_tokens=44_107 * 2000,
                     cost_usd=Decimal("247"))
        assert model_routing_opportunity([pair], _catalog()) == []

    def test_cross_provider_not_considered(self):
        # haiku (anthropic) must not be suggested as a target for an OpenAI pair.
        opps = model_routing_opportunity([_pair()], _catalog())
        assert all(o.to_model != "claude-3-5-haiku-20241022" for o in opps)
        assert all(o.from_provider == "openai" for o in opps)

    def test_confidence_low_for_small_volume(self):
        pair = _pair(requests=9_999, input_tokens=9_999 * 1500, output_tokens=9_999 * 300,
                     cost_usd=Decimal("60"))
        opps = model_routing_opportunity([pair], _catalog())
        assert opps[0].confidence == "low"

    def test_confidence_boundary(self):
        assert model_routing_opportunity(
            [_pair(requests=10_001)], _catalog())[0].confidence == "medium"
        assert model_routing_opportunity(
            [_pair(requests=10_000)], _catalog())[0].confidence == "low"

    def test_sorted_by_savings_desc(self):
        big = _pair(cost_usd=Decimal("350"))
        small = _pair(application="Support Agent", requests=16_375,
                      input_tokens=16_375 * 4000, output_tokens=16_375 * 1000,
                      cost_usd=Decimal("262"))
        opps = model_routing_opportunity([small, big], _catalog())
        assert [o.application for o in opps] == ["Classification", "Support Agent"]
        assert opps[0].est_savings_usd_mo > opps[1].est_savings_usd_mo

    def test_savings_labeled_estimate_in_detail(self):
        opp = model_routing_opportunity([_pair()], _catalog())[0]
        assert "Estimate" in opp.detail["note"]

    def test_unknown_model_skipped_never_invented(self):
        pair = _pair(model="gpt-99", cost_usd=Decimal("500"))
        assert model_routing_opportunity([pair], _catalog()) == []
