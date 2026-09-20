# Phase 8 — Stripe billing: verified API notes

Researched 2026-09-21. Verified against (a) the installed `stripe` Python SDK
v15.6.1 (signatures and object fields inspected directly from the package),
(b) Stripe's public API reference via community citations of
`docs.stripe.com/api/checkout/sessions/create`, and (c) webhook verification
references citing Stripe's webhook docs. No live Stripe calls were made.

## SDK surface (stripe 15.6.1, verified from the installed package)

- Client: `StripeClient(api_key)`. In v15 the bare `client.checkout` /
  `client.billing_portal` accessors are **deprecated** — use the
  `client.v1.*` namespace: `client.v1.checkout.sessions.create(params={...})`.
- Checkout Session object fields include: `id`, `url`, `status`
  (`"open" | "complete" | "expired"`), `mode`, `customer`, `subscription`,
  `payment_status`, `metadata`, `client_reference_id`, `success_url`,
  `cancel_url`.
- Billing Portal: `client.v1.billing_portal.sessions.create(params={"customer": ...,
  "return_url": ...})` → Session with `url`.
- Customers: `client.v1.customers.create(params={"email": ..., "metadata": {...}})`.
- Subscriptions: `client.v1.subscriptions.retrieve(sub_id)` → object with
  `status`, `customer`, `id`, `metadata`, `trial_end`, `items`.
- Webhooks: `stripe.Webhook.construct_event(payload: bytes|str, sig_header: str,
  secret: str)` — raises `stripe.SignatureVerificationError` on bad signature;
  default timestamp tolerance 300s. Test helper:
  `stripe.WebhookSignature.generate_signature_header(payload, secret, timestamp)`.
- Subscription statuses (standard): `trialing`, `active`, `past_due`,
  `canceled`, `unpaid`, `incomplete`, `incomplete_expired`, `paused`.

## Checkout Sessions (subscription mode)

- `mode="subscription"` creates a Subscription + first Invoice + PaymentIntent.
- Required params: `line_items=[{"price": <price_id>, "quantity": 1}]`,
  `success_url`, `cancel_url`.
- `success_url` supports the `{CHECKOUT_SESSION_ID}` template placeholder.
- Identify the org via `metadata={"org_id": ..., "plan": ...}` on the session
  AND `subscription_data={"metadata": {...}}` — the latter persists on the
  Subscription object so all future subscription/invoice webhooks carry it.
- For an existing customer pass `customer=<cus_id>`; for a new one pass
  `customer_email` (Stripe creates the customer) — we create the Customer
  ourselves first so we can store `stripe_customer_id` on the org.
- Idempotency: pass an idempotency key via request options on retry; we
  additionally reuse an org's still-`open` session to make double-clicks safe.

## Webhooks

- Stripe signs with HMAC-SHA256; header `stripe-signature: t=...,v1=...`.
- **Must read the raw request body** (bytes) before any JSON parsing; FastAPI:
  `await request.body()`.
- Events we handle:
  - `checkout.session.completed` → `session.subscription`, `session.customer`
    are set; metadata carries our org_id/plan.
  - `customer.subscription.updated` → full Subscription; plan derived from
    `items.data[0].price.id` mapped through our env price IDs.
  - `customer.subscription.deleted` → treat as canceled.
  - `invoice.payment_failed` → mark past_due (find org via `invoice.customer`).
- Always return 200 for verified events we intentionally ignore (unknown org,
  unknown type) — 4xx/5xx makes Stripe retry.
- Dedupe on `event.id` — Stripe redelivers; store processed IDs.

## Assumptions / deliberate choices

- Prices are created in the Stripe Dashboard; only the Price IDs travel via
  env (`STRIPE_PRICE_STARTER`, `STRIPE_PRICE_GROWTH`). No price_data inline —
  keeps catalog changes out of deploys.
- No usage-based (metered) billing in v0.1: flat monthly plans; event counts
  are metered for soft limit warnings only.
- Trial is time-based (14d), no card — modeled as `organizations.trial_ends_at`,
  not a Stripe trial, so no Stripe objects exist during trial.
- Customer Portal handles upgrades/downgrades/cancellation UI — we only
  reflect webhook state; we don't build plan-change endpoints in v0.1.
- `past_due` keeps paid access (grace) but is surfaced in billing status.

## References

- https://docs.stripe.com/api/checkout/sessions/create
- https://docs.stripe.com/api/customer_portal/sessions/create
- https://docs.stripe.com/webhooks/signature
- https://docs.stripe.com/billing/subscriptions/overview
- SDK migration note: https://github.com/stripe/stripe-python/wiki/v1-namespace-in-StripeClient
