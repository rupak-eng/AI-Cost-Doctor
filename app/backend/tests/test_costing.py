"""Unit tests for the deterministic cost engine (no DB required)."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.services.costing import (
    Price,
    PriceNotFoundError,
    event_cost,
    load_catalog,
    price_for,
    resolve_cost,
    REPORTED,
    CALCULATED,
)


def _price(**kw):
    base = dict(provider="openai", model="gpt-4.1",
                input_usd_per_1m=Decimal("2.00"), output_usd_per_1m=Decimal("8.00"),
                cached_input_usd_per_1m=Decimal("0.50"), reasoning_usd_per_1m=None,
                effective_from=date(2025, 4, 14), effective_to=None, source="catalog")
    base.update(kw)
    return Price(**base)


class TestExactArithmetic:
    def test_gpt41_support_agent_request(self):
        # 4000 in / 1000 out on gpt-4.1 ($2/$8 per 1M) = $0.016 exactly.
        cost = event_cost(input_tokens=4000, output_tokens=1000, price=_price())
        assert cost == Decimal("0.016")
        assert isinstance(cost, Decimal)

    def test_classification_request(self):
        # 1500 in / 300 out = 0.003 + 0.0024 = $0.0054 exactly.
        cost = event_cost(input_tokens=1500, output_tokens=300, price=_price())
        assert cost == Decimal("0.0054")

    def test_mini_request(self):
        mini = _price(model="gpt-4.1-mini", input_usd_per_1m=Decimal("0.40"),
                      output_usd_per_1m=Decimal("1.60"), cached_input_usd_per_1m=Decimal("0.10"))
        cost = event_cost(input_tokens=6000, output_tokens=2000, price=mini)
        assert cost == Decimal("0.0056")

    def test_no_float_drift_over_many_events(self):
        # Summing 100k identical per-event costs must equal 100k x unit cost.
        mini = _price(model="gpt-4.1-mini", input_usd_per_1m=Decimal("0.40"),
                      output_usd_per_1m=Decimal("1.60"))
        unit = event_cost(input_tokens=4000, output_tokens=1000, price=mini)
        total = sum((event_cost(input_tokens=4000, output_tokens=1000, price=mini)
                     for _ in range(100_000)), Decimal(0))
        assert total == unit * 100_000
        assert total == Decimal("320.00000000")  # 100k x $0.0032

    def test_cached_and_reasoning_variants(self):
        p = _price(cached_input_usd_per_1m=Decimal("0.50"), reasoning_usd_per_1m=Decimal("3.00"))
        cost = event_cost(input_tokens=1000, output_tokens=500, price=p,
                          cached_input_tokens=2000, reasoning_tokens=100)
        # 0.002 + 0.004 + 0.001 + 0.0003
        assert cost == Decimal("0.0073")

    def test_zero_tokens(self):
        assert event_cost(input_tokens=0, output_tokens=0, price=_price()) == Decimal(0)

    def test_negative_tokens_rejected(self):
        with pytest.raises(ValueError):
            event_cost(input_tokens=-1, output_tokens=0, price=_price())

    def test_missing_variant_price_raises_not_invents(self):
        p = _price(cached_input_usd_per_1m=None)
        with pytest.raises(PriceNotFoundError):
            event_cost(input_tokens=0, output_tokens=0, price=p, cached_input_tokens=10)


class TestEffectiveDateSelection:
    def _catalog(self):
        return [
            _price(effective_from=date(2025, 1, 1), effective_to=date(2026, 1, 1),
                   input_usd_per_1m=Decimal("3.00"), output_usd_per_1m=Decimal("12.00")),
            _price(effective_from=date(2026, 1, 1), effective_to=None,
                   input_usd_per_1m=Decimal("2.00"), output_usd_per_1m=Decimal("8.00")),
        ]

    def test_picks_price_effective_at_event_time(self):
        catalog = self._catalog()
        p = price_for(catalog, provider="openai", model="gpt-4.1",
                      at=datetime(2025, 6, 1, tzinfo=timezone.utc))
        assert p.input_usd_per_1m == Decimal("3.00")

    def test_boundary_effective_from_inclusive(self):
        catalog = self._catalog()
        p = price_for(catalog, provider="openai", model="gpt-4.1",
                      at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
        assert p.input_usd_per_1m == Decimal("2.00")

    def test_boundary_effective_to_exclusive(self):
        catalog = self._catalog()
        p = price_for(catalog, provider="openai", model="gpt-4.1",
                      at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        assert p.input_usd_per_1m == Decimal("3.00")

    def test_no_covering_price_raises(self):
        with pytest.raises(PriceNotFoundError):
            price_for(self._catalog(), provider="openai", model="gpt-4.1",
                      at=datetime(2024, 1, 1, tzinfo=timezone.utc))

    def test_unknown_model_raises(self):
        with pytest.raises(PriceNotFoundError):
            price_for(self._catalog(), provider="openai", model="nope",
                      at=datetime(2025, 6, 1, tzinfo=timezone.utc))


class TestCatalogFile:
    def test_real_prices_present(self):
        catalog = load_catalog()
        by_key = {(p.provider, p.model): p for p in catalog}
        assert by_key[("openai", "gpt-4.1")].input_usd_per_1m == Decimal("2.00")
        assert by_key[("openai", "gpt-4.1")].output_usd_per_1m == Decimal("8.00")
        assert by_key[("openai", "gpt-4.1-mini")].input_usd_per_1m == Decimal("0.40")
        assert by_key[("openai", "gpt-4.1-mini")].output_usd_per_1m == Decimal("1.60")
        assert by_key[("anthropic", "claude-3-5-haiku-20241022")].input_usd_per_1m == Decimal("0.80")
        assert by_key[("anthropic", "claude-3-5-haiku-20241022")].output_usd_per_1m == Decimal("4.00")

    def test_prices_are_decimal_not_float(self):
        for p in load_catalog():
            assert isinstance(p.input_usd_per_1m, Decimal)
            assert isinstance(p.output_usd_per_1m, Decimal)


class TestReportedVsCalculatedLabeling:
    def test_reported_wins_when_present(self):
        value, label = resolve_cost(Decimal("1.23"), Decimal("1.20"))
        assert value == Decimal("1.23") and label == REPORTED

    def test_calculated_fallback(self):
        value, label = resolve_cost(None, Decimal("1.20"))
        assert value == Decimal("1.20") and label == CALCULATED

    def test_neither_is_none(self):
        value, label = resolve_cost(None, None)
        assert value is None and label is None

    def test_labels_never_silent(self):
        # The label must always travel with the value.
        for reported, calculated in [(Decimal("1"), None), (None, Decimal("2"))]:
            value, label = resolve_cost(reported, calculated)
            assert value is not None and label in (REPORTED, CALCULATED)
