# Implementation Plan (revised — demo-first)

**Date:** 2026-09-21 (revised) · Maps to the approved product hierarchy and
phase order from the 2026-09-21 build brief.

**Product hierarchy (fixed):**
1. Per-customer AI unit economics / Tenant P&L — spearhead
2. Cost diagnosis — core engine
3. Savings recommendations — monetization / value proof
4. General cost analytics — supporting feature

**Positioning rule:** lead with "AI unit economics", "customer profitability",
"margin killers", "cost diagnosis", "potential savings", "root cause".
Never position as "LLM observability platform", "AI monitoring platform",
or "another dashboard". Observability may be mentioned only as a data source.

**Demo-first principle:** the same backend cost engine and investigation
logic must power both demo mode (clearly labeled synthetic data) and real
customer data. No hardcoded P&L figures anywhere — every demo metric is
computed deterministically from seeded usage events. Replacing the synthetic
dataset with real data must not require rewriting product logic.

## Phase 1 — Repository architecture + database + seed/demo dataset

- Monorepo scaffold: `app/docker-compose.yml` (services: `web`, `api`,
  `worker`, `postgres:16`), `app/backend` (FastAPI), `app/frontend`
  (Next.js 14, TypeScript, Tailwind), `app/worker` (same image as backend,
  scheduler entrypoint). No Redis, no queue, no microservices.
- PostgreSQL schema per `02-architecture.md` §3 **plus** a `tenants` table:
  `tenants (id uuid pk, org_id uuid, project_id uuid→projects,
  external_id text, name text, monthly_revenue_usd numeric,
  plan text, created_at timestamptz, unique(org_id, external_id))`
  — `usage_events.tenant_id` references `tenants.external_id`.
- `costing.py`: deterministic cost engine (single place prices → dollars),
  versioned pricing catalog seeded from JSON, with unit tests (price ×
  tokens math, effective-date boundaries, reported vs calculated labeling).
- Demo seed (`backend/app/seed_demo.py`): a labeled "DemoCo" org with 3
  tenants + 30 days of usage events calibrated so the cost engine produces
  (tolerance ±5%):
  - **Customer A** — revenue $499/mo, AI cost ≈ $681/mo, margin ≈ -$182/mo,
    status `margin_killer`. ~73% of cost from the **Support Agent**;
    ~81% of Support Agent cost from **GPT-4.1**. Includes a classification
    workflow on GPT-4.1 whose routing to a cheaper model saves ≈ $140/mo
    (post-change margin ≈ -$42/mo, confidence Medium).
  - **Customer B** — revenue $299/mo, AI cost ≈ $247/mo, margin ≈ +$52/mo.
  - **Customer C** — revenue $799/mo, AI cost ≈ $741/mo, margin ≈ +$58/mo.
- Demo APIs (all responses carry `"data_label": "demo"`):
  - `GET /api/v1/demo/pnl` → per-tenant revenue, AI cost, margin, status.
  - `POST /api/v1/demo/investigate {tenant_external_id}` → deterministic
    root-cause facts: cost by model, by application, volume-vs-token change,
    expensive workflows, recommended action, estimated monthly savings,
    confidence. Template-generated narrative (no LLM in v0.1 demo).
- **Done when:** compose file defined; migrations clean; `costing.py` tests
  green; seed produces P&L within tolerance of the targets above; every
  demo API number traces to seeded events.

## Phase 2 — Landing page + demo experience + auth

- Landing page: serious US/UK B2B SaaS aesthetic — no excessive gradients,
  no childish illustration. Hero: **"Find where your AI budget is leaking."**
  Two CTAs: **"Analyze My AI Spend"** → signup/onboarding, **"See How It
  Works"** → interactive demo (no API key, no signup).
- Demo experience: Customer P&L view (revenue, AI cost, gross AI margin,
  status e.g. "Margin Killer") → click customer → Investigate view
  (root-cause breakdown, recommended action, estimated savings, confidence).
  Prominent **"Demo data"** labeling on every view.
- Auth: signup/login with JWT (+ refresh), org + first project creation,
  protected app shell. Empty-state dashboard for new orgs.
- **Done when:** landing → demo → P&L → margin killer → investigate →
  root cause → recommendation → savings works end-to-end on the seed data.

## Phase 3 — CSV ingestion + event API

- CSV upload with guided column mapping (timestamp, provider, model, app,
  tenant, input/output tokens, cost) + dry-run preview showing parsed rows
  and computed cost before commit.
- `POST /api/v1/ingest/events` with per-project API keys (hashed at rest,
  shown once at creation). Minimal 8-field payload documented.
- **Done when:** the Phase 2 success flow works identically with uploaded
  CSV data (P&L → investigate → savings), not just the seed.

## Phase 4 — OpenAI + Anthropic integrations

- **Before building:** verify current API auth, permissions, and available
  usage/cost granularity from primary provider documentation. Do NOT invent
  integrations — if a provider API cannot supply a field, the UI says so
  and CSV/event ingest is the honest fallback.
- Encrypted credential store (envelope encryption, never plaintext) +
  OpenAI connector (Costs + usage APIs) and Anthropic connector
  (Admin Usage + Cost APIs; dual-key onboarding UI).
- Sync worker (daily provider pull) with "data as of" labeling; never
  imply real-time.
- Bill-reconciliation view: provider-reported vs our calculated cost per
  day, drift flag > 5%.

## Phase 5 — Cost engine + dashboard + tenant P&L

- Generalize the Phase 1 cost engine to all orgs/projects (same code path
  the demo uses). Recompute/backfill support when the catalog changes.
- Dashboard: total spend, this/last month, Δ%, projected month-end,
  requests, tokens, avg cost/request, cost by provider/model/application/
  tenant, spend over time. Cost explorer with all filters + CSV export.
- Tenant P&L for real data: tenant revenue input via settings/CSV/event
  metadata; margin-killer list. All UI cost labels keep the
  **Reported / Calculated / Estimated** distinction.
- **Done when:** demo org and a real org show identical-shape results from
  the same engine; every number traceable to events.

## Phase 6 — Anomaly detection

- Deterministic 7-day vs 28-day robust detection per dimension (overall,
  provider, model, application, tenant) with contribution attribution —
  per `02-architecture.md` §7. Nightly worker scan + on-demand scan.
- Slack/email alerts; alert test button.
- **Done when:** synthetic spike/drift/no-op fixtures produce exactly the
  expected anomalies (asserted in tests).

## Phase 7 — Investigate + savings recommendations

- Rules engine: model routing, prompt caching, token hygiene — each with
  current cost/mo, **estimated** monthly savings (labeled as estimates,
  never guaranteed), confidence, qualitative quality-risk note.
- Investigate flow generalized from the demo: fact-gathering →
  `narrator.py` (LLM writes prose from supplied facts only; numbers are
  never computed by the LLM; template fallback on validation failure).
- Wire anomaly → Investigate → recommendation into one click-path.
- **Done when:** on demo data, "Why did spend increase?" returns the
  correct driver, a sensible action, and savings within 10% of the
  fixture's ground truth.

## Phase 8 — Billing

- Stripe: checkout, webhooks, plan gating (Free / Starter $49 / Growth
  $149 / Scale $399 per wedge doc), billing portal.
- **Done when:** test-mode subscription upgrades/downgrades gate features
  correctly.

## Phase 9 — Mac companion app (after web demand)

- Menu-bar app (Swift/SwiftUI): today's spend + Δ%, top driver, spike
  notifications, "Investigate" deep link to web. Read-only API token.
- Explicitly last — the web SaaS must demonstrate demand first.

## Cross-phase rules (binding)

- End every phase with: compose stack defined and green where runnable,
  migrations clean, demo flow working, docs updated, tests passing.
- Never present demo/synthetic data as real; never present estimates as
  guaranteed savings; never invent an integration — if a provider API can't
  do it, say so in the UI.
- Never store secrets in plaintext. No SOC 2 / GDPR / HIPAA claims until
  implemented and verified. Multi-tenant from day one (`org_id` + RLS).
- Deterministic arithmetic is tested exactly; LLM is prose-only with a
  template fallback.
- MVP success criterion (before expanding the feature set): the full flow
  **landing → demo → customer P&L → margin killer → investigate → root
  cause → recommended action → estimated savings** works, and then the same
  flow works with uploaded CSV data.

## API contract (Phase 1–2, stable across phases)

Base: `/api/v1`. Auth: `Authorization: Bearer <JWT>` for user endpoints;
`X-API-Key: <project key>` for ingest. All money in USD decimals; all
timestamps ISO-8601 UTC.

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/signup` | `{email, password, org_name}` → tokens + user + org + project |
| POST | `/auth/login` | `{email, password}` → tokens + user + org |
| POST | `/auth/refresh` | `{refresh_token}` → new token pair |
| GET | `/auth/me` | current user + org + projects |
| GET | `/demo/pnl` | `[{tenant_id, name, revenue_usd, ai_cost_usd, margin_usd, status}]` + `"data_label":"demo"` |
| POST | `/demo/investigate` | `{tenant_external_id}` → `{summary, drivers:{by_model[], by_app[]}, volume_vs_tokens{}, expensive_workflows[], recommendation{action, est_savings_usd_mo, confidence, post_change_margin_usd}}` + `"data_label":"demo"` |
| POST | `/ingest/events` | project API key; batch of usage events (Phase 3) |
| POST | `/integrations/csv/upload` | multipart + column map (Phase 3) |

Tenant `status` values: `margin_killer` (margin < 0), `at_risk` (margin <
15% of revenue), `healthy`.
