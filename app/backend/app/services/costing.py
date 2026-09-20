"""Deterministic cost engine — the single place prices turn into dollars.

Rules (spec 02 §6):
- Per event: input_tokens/1M × input_price + output_tokens/1M × output_price
  (+ cached-input / reasoning variants when present), using the price row
  effective at the event's timestamp.
- All arithmetic in Decimal. Division is only ever by 1_000_000 (a power of
  ten), so Decimal arithmetic is exact — no float drift, ever.
- Labels, always: Reported (provider's number) · Calculated (our catalog
  math) · Estimated (modeled/forecast). Never mixed silently.

Nothing else in the codebase hardcodes a price.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ONE_MILLION = Decimal(1_000_000)
CATALOG_PATH = Path(__file__).with_name("pricing_catalog.json")


class PriceNotFoundError(LookupError):
    """Raised when no catalog price covers (provider, model) at the given time.

    We never invent a price — callers must surface this as missing data.
    """


@dataclass(frozen=True)
class Price:
    provider: str
    model: str
    input_usd_per_1m: Decimal
    output_usd_per_1m: Decimal
    cached_input_usd_per_1m: Decimal | None
    reasoning_usd_per_1m: Decimal | None
    effective_from: date
    effective_to: date | None  # None = current
    source: str = "catalog"

    def covers(self, at: date) -> bool:
        return self.effective_from <= at and (self.effective_to is None or at < self.effective_to)


def _dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def load_catalog(path: Path | str = CATALOG_PATH) -> list[Price]:
    """Load the versioned pricing catalog from JSON. Prices stay Decimal."""
    data = json.loads(Path(path).read_text())
    prices = []
    for row in data["prices"]:
        prices.append(Price(
            provider=row["provider"],
            model=row["model"],
            input_usd_per_1m=Decimal(row["input_usd_per_1m"]),
            output_usd_per_1m=Decimal(row["output_usd_per_1m"]),
            cached_input_usd_per_1m=_dec(row.get("cached_input_usd_per_1m")),
            reasoning_usd_per_1m=_dec(row.get("reasoning_usd_per_1m")),
            effective_from=date.fromisoformat(row["effective_from"]),
            effective_to=date.fromisoformat(row["effective_to"]) if row.get("effective_to") else None,
            source=row.get("source", "catalog"),
        ))
    return prices


def price_for(catalog: list[Price], *, provider: str, model: str, at: datetime | date) -> Price:
    """Select the price row effective at `at`.

    Boundary rule: effective_from <= at < effective_to. When rows overlap,
    the one with the latest effective_from wins.
    """
    at_date = at.date() if isinstance(at, datetime) else at
    candidates = [p for p in catalog
                  if p.provider == provider and p.model == model and p.covers(at_date)]
    if not candidates:
        raise PriceNotFoundError(
            f"no price for {provider}/{model} effective at {at_date}")
    return max(candidates, key=lambda p: p.effective_from)


def event_cost(*, input_tokens: int, output_tokens: int, price: Price,
               cached_input_tokens: int = 0, reasoning_tokens: int = 0) -> Decimal:
    """Exact per-event cost in USD. All Decimal; no float anywhere."""
    if input_tokens < 0 or output_tokens < 0 or cached_input_tokens < 0 or reasoning_tokens < 0:
        raise ValueError("token counts must be non-negative")
    total = (Decimal(input_tokens) * price.input_usd_per_1m
             + Decimal(output_tokens) * price.output_usd_per_1m)
    if cached_input_tokens:
        if price.cached_input_usd_per_1m is None:
            raise PriceNotFoundError(
                f"no cached-input price for {price.provider}/{price.model}")
        total += Decimal(cached_input_tokens) * price.cached_input_usd_per_1m
    if reasoning_tokens:
        if price.reasoning_usd_per_1m is None:
            raise PriceNotFoundError(
                f"no reasoning price for {price.provider}/{price.model}")
        total += Decimal(reasoning_tokens) * price.reasoning_usd_per_1m
    return total / ONE_MILLION


# ---------------------------------------------------------------------------
# Reported vs calculated vs estimated labeling
# ---------------------------------------------------------------------------

REPORTED = "reported"      # the provider's own number for the event/bucket
CALCULATED = "calculated"  # our deterministic catalog math
ESTIMATED = "estimated"    # modeled/forecast — never presented as fact


def resolve_cost(cost_reported_usd: Decimal | None,
                 cost_calculated_usd: Decimal | None) -> tuple[Decimal | None, str | None]:
    """Return (value, label) for display.

    Reported wins when present (it's the provider's ground truth for that
    event); otherwise we fall back to our calculated cost. The label always
    travels with the value so the UI can never mix them silently.
    """
    if cost_reported_usd is not None:
        return cost_reported_usd, REPORTED
    if cost_calculated_usd is not None:
        return cost_calculated_usd, CALCULATED
    return None, None


def ensure_catalog_in_db(db, catalog: list[Price] | None = None) -> int:
    """Idempotent upsert of the JSON catalog into model_prices. Returns rows added."""
    from app import models as m  # deferred to avoid import cycles

    catalog = catalog if catalog is not None else load_catalog()
    added = 0
    for p in catalog:
        exists = (
            db.query(m.ModelPrice)
            .filter_by(provider=p.provider, model=p.model, effective_from=p.effective_from)
            .first()
        )
        if exists:
            continue
        db.add(m.ModelPrice(
            provider=p.provider, model=p.model,
            input_usd_per_1m=p.input_usd_per_1m, output_usd_per_1m=p.output_usd_per_1m,
            cached_input_usd_per_1m=p.cached_input_usd_per_1m,
            reasoning_usd_per_1m=p.reasoning_usd_per_1m,
            effective_from=p.effective_from, effective_to=p.effective_to,
            source=p.source,
        ))
        added += 1
    db.flush()
    return added
