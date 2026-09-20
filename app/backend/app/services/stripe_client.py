"""Thin seam over the Stripe Python SDK.

All Stripe API calls go through :func:`get_stripe_client` so tests can
monkeypatch this module without touching the network. Uses the ``v1``
namespace (the bare ``client.checkout`` style is deprecated in stripe>=15).

Secrets come from env via app.core.config — never from the DB, logs, or
API responses.
"""
from __future__ import annotations

from app.core.config import settings

try:
    from stripe import StripeClient
except ImportError:  # pragma: no cover - stripe is a hard requirement in prod
    StripeClient = None  # type: ignore[assignment]


def stripe_configured() -> bool:
    """True when a Stripe secret key is present (checkout/portal usable)."""
    return bool(settings.stripe_secret_key) and StripeClient is not None


def webhook_configured() -> bool:
    return bool(settings.stripe_webhook_secret)


def get_stripe_client():
    """Return a StripeClient, or raise if billing is not configured.

    Fresh client per call on purpose: tests monkeypatch this module's
    functions, and a cached instance would bypass the seam.
    """
    if not stripe_configured():
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
    return StripeClient(settings.stripe_secret_key)
