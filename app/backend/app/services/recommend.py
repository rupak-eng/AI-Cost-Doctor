"""Rules-based savings recommendations — deterministic, dollar-quantified.

Generators (each emits Recommendation objects, sorted by estimated savings):

- `model_routing_opportunity`: for each (application, model) pair above a
  monthly cost threshold, if a cheaper same-provider model exists in the
  pricing catalog, estimate the savings of shifting traffic::

      est_savings = (price_delta_per_token x pair_tokens) x shiftable_share

  where price_delta is computed per token class (input/output/cached/
  reasoning) from the catalog prices current *now* (recommendations are
  forward-looking), and shiftable_share (default 50%) is the conservative
  fraction of the pair's traffic assumed routable without quality review.
  Never recommends across providers.

- `prompt_caching_opportunity`: ONLY fires when the usage data itself shows
  cacheable patterns — i.e. the pair already has observed cached_input_tokens
  (proof the workload hits the provider's prompt cache) but caches less than
  80% of its input tokens. Estimates the savings of extending caching to more
  of the input stream. When no cache usage is observed the generator emits
  nothing rather than guessing about prompt repeatability.

- `anomaly_followup_opportunity`: for open cost anomalies already detected
  for the tenant (see services/anomalies.py) — a pointer recommendation
  whose estimated value is the anomaly's observed dollar delta. Pure join
  over existing deterministic rows; no new math.

All savings are labeled ESTIMATES — never guaranteed. Confidence is
data-coverage based: high when the pair served > 1,000 requests in-window
(enough volume to trust the token mix), medium when > 100, else low.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.services.costing import Price, PriceNotFoundError, event_cost, load_catalog

#: Carried on every recommendation, in the API schema and the UI.
DISCLAIMER = "Estimates are not guarantees."

#: Minimum projected monthly savings for a recommendation to be emitted.
MIN_SAVINGS_USD_MO = Decimal("10")


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


@dataclass(frozen=True)
class Recommendation:
    """One deterministic savings recommendation.

    `est_savings_usd_mo` is an ESTIMATE computed from observed usage and
    catalog prices — never a guarantee (see DISCLAIMER, always attached).
    """
    type: str  # model_routing | prompt_caching | anomaly_followup
    title: str
    action: str
    explanation: str
    est_savings_usd_mo: Decimal
    confidence: str  # high|medium|low
    detail: dict = field(default_factory=dict)
    disclaimer: str = DISCLAIMER


def _confidence_for_volume(requests: int) -> str:
    """Data-coverage confidence: high when > 1,000 requests observed."""
    if requests > 1_000:
        return "high"
    if requests > 100:
        return "medium"
    return "low"


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
        opportunities.append(RoutingOpportunity(
            application=pair.application,
            from_provider=pair.provider,
            from_model=pair.model,
            to_model=to_model,
            requests_per_mo=pair.requests,
            current_cost_usd_mo=pair.cost_usd,
            est_savings_usd_mo=est_savings,
            confidence=_confidence_for_volume(pair.requests),
            detail={
                "shiftable_share": str(share),
                "full_price_delta_usd_mo": str(full_delta.quantize(Decimal("0.01"))),
                "note": ("Estimate only — assumes the cheaper model meets quality bar. "
                         "Validate on a traffic sample before shifting production."),
            },
        ))
    opportunities.sort(key=lambda o: o.est_savings_usd_mo, reverse=True)
    return opportunities


def prompt_caching_opportunity(
    pairs: list[PairStats],
    catalog: list[Price] | None = None,
    *,
    # Conservative share of the still-uncached input stream assumed to be
    # repeated prefixes the provider cache could absorb. Documented, not
    # measured — confidence stays low/medium accordingly.
    additional_cacheable_share: Decimal | float = Decimal("0.25"),
) -> list[RoutingOpportunity]:
    """Find prompt-caching expansion opportunities.

    Fires ONLY when the pair's own usage data proves cacheability: observed
    cached_input_tokens > 0 (the provider cache is already being hit) while
    the cached share of input tokens is below 80%. No cache usage observed
    -> no recommendation, rather than guessing about prompt repeatability.
    """
    catalog = catalog if catalog is not None else load_catalog()
    share = Decimal(str(additional_cacheable_share))
    current = _current_prices(catalog)

    opportunities: list[RoutingOpportunity] = []
    for pair in pairs:
        if pair.requests <= 0 or pair.input_tokens <= 0:
            continue
        if pair.cached_input_tokens <= 0:
            continue  # no observed cache hits — cannot prove cacheability; skip
        cached_share = pair.cached_input_tokens / pair.input_tokens
        if cached_share >= 0.80:
            continue  # already caching nearly everything
        price = current.get((pair.provider, pair.model))
        if price is None:
            continue  # unknown model — never invent a price; skip
        if price.cached_input_usd_per_1m is None:
            continue  # model has no cached-input rate — skip
        rate_delta_per_1m = price.input_usd_per_1m - price.cached_input_usd_per_1m
        if rate_delta_per_1m <= 0:
            continue
        uncached_input = pair.input_tokens - pair.cached_input_tokens
        est_savings = (Decimal(uncached_input) * rate_delta_per_1m
                       / Decimal(1_000_000) * share).quantize(Decimal("0.01"))
        if est_savings < MIN_SAVINGS_USD_MO:
            continue
        confidence = "medium" if pair.cached_input_tokens >= 100_000 else "low"
        opportunities.append(RoutingOpportunity(
            application=pair.application,
            from_provider=pair.provider,
            from_model=pair.model,
            to_model=pair.model,  # same model — the lever is caching, not routing
            requests_per_mo=pair.requests,
            current_cost_usd_mo=pair.cost_usd,
            est_savings_usd_mo=est_savings,
            confidence=confidence,
            detail={
                "cached_input_share": f"{cached_share:.1%}",
                "additional_cacheable_share": str(share),
                "uncached_input_tokens": uncached_input,
                "note": ("Estimate only — assumes a share of the uncached input "
                         "stream consists of repeated prefixes the provider cache "
                         "can absorb. Validate cache hit rates before projecting."),
            },
        ))
    opportunities.sort(key=lambda o: o.est_savings_usd_mo, reverse=True)
    return opportunities


def to_recommendation(
    opp: RoutingOpportunity, *, kind: str, title: str, action: str, explanation: str,
) -> Recommendation:
    """Shape a RoutingOpportunity (routing or caching) as a Recommendation."""
    return Recommendation(
        type=kind,
        title=title,
        action=action,
        explanation=explanation,
        est_savings_usd_mo=opp.est_savings_usd_mo,
        confidence=opp.confidence,
        detail={**opp.detail, "application": opp.application,
                "from_model": opp.from_model, "to_model": opp.to_model,
                "current_cost_usd_mo": str(opp.current_cost_usd_mo)},
    )


def routing_recommendation(opp: RoutingOpportunity) -> Recommendation:
    """Shape a model-routing opportunity as a customer-facing Recommendation."""
    return to_recommendation(
        opp,
        kind="model_routing",
        title=f"Route {opp.application} to {opp.to_model}",
        action=(f"Route suitable {opp.application} requests from {opp.from_model} "
                f"to {opp.to_model} (lower-cost model)"),
        explanation=(f"{opp.application} on {opp.from_model} costs "
                     f"${opp.current_cost_usd_mo:,.2f}/mo. {opp.to_model} is a "
                     f"cheaper same-provider model; shifting part of this traffic "
                     f"could save ~${opp.est_savings_usd_mo:,.2f}/mo if quality holds."),
    )


def caching_recommendation(opp: RoutingOpportunity) -> Recommendation:
    """Shape a prompt-caching opportunity as a customer-facing Recommendation."""
    return to_recommendation(
        opp,
        kind="prompt_caching",
        title=f"Expand prompt caching on {opp.from_model}",
        action=(f"Extend prompt-cache coverage for {opp.application} on "
                f"{opp.from_model} (currently {opp.detail['cached_input_share']} "
                f"of input tokens served from cache)"),
        explanation=(f"Cache hits are already observed on this workload, so the "
                     f"prompts are provably cacheable. Absorbing more repeated "
                     f"prefixes into the provider cache could save "
                     f"~${opp.est_savings_usd_mo:,.2f}/mo."),
    )
