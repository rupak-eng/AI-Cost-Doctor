"""Rules-based savings recommendations — deterministic, dollar-quantified.

The flagship rule is `model_routing_opportunity`: for each (application,
model) pair above a monthly cost threshold, if a cheaper same-provider model
exists in the pricing catalog, estimate the savings of shifting traffic:

    est_savings = (price_delta_per_token x pair_tokens) x shiftable_share

where price_delta is computed per token class (input/output/cached/reasoning)
from the catalog prices current *now* (recommendations are forward-looking),
and shiftable_share (default 50%) is the conservative fraction of the pair's
traffic assumed routable without quality review.

Savings are labeled ESTIMATES — never guaranteed. Confidence is Medium when
the pair serves > 10k requests/month (enough volume to trust the token mix),
else Low.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.services.costing import Price, PriceNotFoundError, event_cost, load_catalog


@dataclass(frozen=True)
class PairStats:
    """Aggregated monthly stats for one (application, model) pair."""
    application: str
    provider: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: Decimal = Decimal(0)


@dataclass(frozen=True)
class RoutingOpportunity:
    application: str
    from_provider: str
    from_model: str
    to_model: str
    requests_per_mo: int
    current_cost_usd_mo: Decimal
    est_savings_usd_mo: Decimal  # ESTIMATE, not guaranteed
    confidence: str  # high|medium|low
    detail: dict


def _pair_cost_with(price: Price, pair: PairStats) -> Decimal:
    """Cost of the pair's token mix at one catalog price.

    Delegates to the single deterministic code path (costing.event_cost) —
    see costing.py for the pricing rule. Raises PriceNotFoundError when the
    price lacks a cached-input/reasoning rate the pair needs; callers treat
    that as "cannot price this alternative" and skip it.
    """
    return event_cost(
        input_tokens=pair.input_tokens,
        output_tokens=pair.output_tokens,
        price=price,
        cached_input_tokens=pair.cached_input_tokens,
        reasoning_tokens=pair.reasoning_tokens,
    )


def _current_prices(catalog: list[Price]) -> dict[tuple[str, str], Price]:
    """Latest effective price per (provider, model) — recommendations price the future."""
    now = datetime.now(timezone.utc).date()
    best: dict[tuple[str, str], Price] = {}
    for p in catalog:
        if not p.covers(now):
            continue
        key = (p.provider, p.model)
        if key not in best or p.effective_from > best[key].effective_from:
            best[key] = p
    return best


def model_routing_opportunity(
    pairs: list[PairStats],
    catalog: list[Price] | None = None,
    *,
    shiftable_share: Decimal | float = Decimal("0.5"),
    min_monthly_cost_usd: Decimal = Decimal("50"),
) -> list[RoutingOpportunity]:
    """Find model-routing savings opportunities across (app, model) pairs.

    Returns opportunities sorted by estimated monthly savings, descending.
    """
    catalog = catalog if catalog is not None else load_catalog()
    share = Decimal(str(shiftable_share))
    current = _current_prices(catalog)

    opportunities: list[RoutingOpportunity] = []
    for pair in pairs:
        if pair.cost_usd < min_monthly_cost_usd or pair.requests <= 0:
            continue
        from_key = (pair.provider, pair.model)
        if from_key not in current:
            continue  # unknown model — never invent a price; skip
        from_price = current[from_key]
        # Cheaper same-provider candidates, priced on this pair's token mix
        # at CURRENT catalog prices (recommendations price the future).
        candidates = []
        for (prov, model), price in current.items():
            if prov != pair.provider or model == pair.model:
                continue
            try:
                from_cost = _pair_cost_with(from_price, pair)
                alt_cost = _pair_cost_with(price, pair)
            except PriceNotFoundError:
                continue
            if alt_cost < from_cost:
                # Per-token price delta x pair tokens (exact rule).
                candidates.append((model, from_cost - alt_cost))
        if not candidates:
            continue
        to_model, full_delta = max(candidates, key=lambda c: c[1])
        est_savings = (full_delta * share).quantize(Decimal("0.01"))
        confidence = "medium" if pair.requests > 10_000 else "low"
        opportunities.append(RoutingOpportunity(
            application=pair.application,
            from_provider=pair.provider,
            from_model=pair.model,
            to_model=to_model,
            requests_per_mo=pair.requests,
            current_cost_usd_mo=pair.cost_usd,
            est_savings_usd_mo=est_savings,
            confidence=confidence,
            detail={
                "shiftable_share": str(share),
                "full_price_delta_usd_mo": str(full_delta.quantize(Decimal("0.01"))),
                "note": ("Estimate only — assumes the cheaper model meets quality bar. "
                         "Validate on a traffic sample before shifting production."),
            },
        ))
    opportunities.sort(key=lambda o: o.est_savings_usd_mo, reverse=True)
    return opportunities
