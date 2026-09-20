# System Architecture (v0.1 MVP)

**Date:** 2026-09-21 · Status: approved-for-build after wedge sign-off
**Principles:** monolith-first, deterministic cost math, LLM only for
narratives, multi-tenant from day one, no fake data, no unneeded services.

## 1. High-level design

```
                    ┌─────────────────────────────────────────────┐
                    │              Next.js frontend               │
                    │   landing · dashboard · explorer ·          │
                    │   investigate · savings · tenant P&L ·      │
                    │   integrations · settings                   │
                    └──────────────┬──────────────────────────────┘
                                   │ HTTPS / JSON (JWT)
                    ┌──────────────▼──────────────────────────────┐
                    │              FastAPI backend                │
                    │  api/v1: auth, projects, integrations,      │
                    │  ingest, costs, anomalies, investigate,     │
                    │  recommendations, alerts                    │
                    │  services: costing, anomaly, recommend,     │
                    │  llm-narrator, billing-sync                 │
                    └──────┬─────────────────────────┬────────────┘
                           │                         │ scheduled jobs
              ┌────────────▼────────┐     ┌──────────▼───────────┐
              │     PostgreSQL      │     │   Worker (in-proc     │
              │  (single database,  │     │   APScheduler)        │
              │   org_id scoping +  │     │  provider sync,       │
              │   RLS defense)      │     │  anomaly scan,        │
              └─────────────────────┘     │  alert dispatch      │
                                          └──────────────────────┘
```

No Redis, no microservices, no message queue in v0.1. The worker runs as a
second container process against the same DB. Scale later, not now.

**Ingestion sources (v0.1):**
1. **OpenAI** — Costs API + usage API (org-level, per project/model/day).
2. **Anthropic** — Admin API: Usage API (token buckets by key/workspace/model)
   + Cost API (daily USD by workspace). Requires a separate admin API key —
   onboarding explains this.
3. **CSV upload** — universal fallback. Guided column mapping
   (timestamp, provider, model, app, tenant, input/output tokens, cost…).
   Also the path for LiteLLM spend-log exports and Bedrock CUR slices.
4. **Event API** — `POST /v1/events` with per-project API key. The only
   source that carries rich per-request metadata (tenant_id, application,
   feature, prompt hash). This is what powers the tenant-P&L spearhead.

**Later (v0.2+):** Bedrock native (CloudWatch metrics + CUR), OTel span
ingest (OpenInference/OpenLLMetry), Portkey/LiteLLM direct connectors.

## 2. Repository layout

```
app/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/                  # migrations
│   └── app/
│       ├── main.py               # FastAPI app, routers
│       ├── core/                 # config, security (jwt, crypto), db session
│       ├── models/               # SQLAlchemy models (see §3)
│       ├── schemas/              # Pydantic request/response
│       ├── api/v1/               # routers: auth, orgs, projects, integrations,
│       │                         # ingest, costs, anomalies, investigate,
│       │                         # recommendations, alerts, demo
│       └── services/
│           ├── ingest/           # openai.py, anthropic.py, csv_import.py, events.py
│           ├── costing.py        # deterministic cost engine + pricing catalog
│           ├── anomaly.py        # 7v28d robust detection (§6)
│           ├── recommend.py      # rules-based savings opportunities (§7)
│           ├── narrator.py       # LLM narrative generation (numbers in, prose out)
│           └── secrets.py        # envelope encryption for provider keys
├── frontend/
│   ├── Dockerfile
│   └── (Next.js 14 app router, TS, Tailwind)
└── worker/  (same image as backend, `python -m app.worker`)
```

## 3. Database schema (PostgreSQL)

Every tenant table carries `org_id`. RLS policies enforce
`org_id = current_setting('app.org_id')` as defense in depth; the app also
scopes every query by org.

```sql
organizations (id uuid pk, name text, slug text unique,
               plan text default 'free', created_at timestamptz)

users         (id uuid pk, org_id uuid→organizations, email citext unique,
               password_hash text, role text /*owner|admin|member*/,
               created_at timestamptz)

projects      (id uuid pk, org_id uuid→organizations, name text,
               created_at timestamptz)

-- Provider credentials: key material NEVER in plaintext.
provider_credentials (
  id uuid pk, org_id uuid→organizations, provider text /*openai|anthropic|...*/,
  label text, encrypted_key bytea, key_last4 text,
  status text /*active|error*/, last_sync_at timestamptz, created_at timestamptz)

-- Per-project keys for the event-ingest API (stored as hash only).
api_keys      (id uuid pk, org_id uuid→organizations, project_id uuid→projects,
               name text, key_hash text, key_prefix text /*for display*/,
               created_at timestamptz, revoked_at timestamptz)

-- Versioned pricing catalog. Cost is always computed with the price
-- effective at the event's timestamp.
model_prices  (id uuid pk, provider text, model text,
               input_usd_per_1m numeric, output_usd_per_1m numeric,
               cached_input_usd_per_1m numeric, reasoning_usd_per_1m numeric,
               effective_from date, effective_to date /*null = current*/,
               source text /*catalog|override*/)

-- One row per LLM call (from event API / proxy logs) or per aggregated
-- bucket (from provider billing APIs, source='provider_api').
usage_events  (id uuid pk, org_id uuid→organizations, project_id uuid→projects,
               source text /*event_api|csv|openai|anthropic*/,
               provider text, model text, application text,
               environment text default 'production', tenant_id text,
               occurred_at timestamptz,
               input_tokens int, output_tokens int,
               cached_input_tokens int default 0, reasoning_tokens int default 0,
               latency_ms int, status text /*ok|error*/,
               provider_request_id text,
               cost_reported_usd numeric   /* what the provider said, if any */,
               cost_calculated_usd numeric /* our deterministic math */,
               metadata jsonb, ingested_at timestamptz)
-- indexes: (org_id, occurred_at), (org_id, project_id, occurred_at),
--          (org_id, tenant_id, occurred_at), (org_id, model, occurred_at)

cost_anomalies (id uuid pk, org_id uuid→organizations, project_id uuid→projects,
               detected_at timestamptz, dimension text /*overall|provider|model|
               application|tenant*/, dimension_value text, metric text,
               baseline_usd numeric, observed_usd numeric, change_pct numeric,
               abs_delta_usd numeric, severity text /*info|warning|critical*/,
               status text /*open|investigated|resolved|dismissed*/,
               evidence jsonb /* contribution breakdown */)

recommendations (id uuid pk, org_id uuid→organizations, project_id uuid→projects,
               type text /*model_routing|prompt_caching|token_hygiene|...*/,
               title text, summary text, detail jsonb,
               current_cost_usd_mo numeric, est_savings_usd_mo numeric,
               confidence text /*high|medium|low*/, status text /*open|applied|dismissed*/,
               created_at timestamptz)

alerts        (id uuid pk, org_id uuid→organizations, project_id uuid→projects,
               name text, channel text /*slack|email*/, config jsonb,
               enabled bool default true)
alert_events  (id uuid pk, alert_id uuid→alerts, anomaly_id uuid→cost_anomalies,
               sent_at timestamptz, payload jsonb)

audit_log     (id uuid pk, org_id uuid→organizations, user_id uuid→users,
               action text, target_type text, target_id text,
               created_at timestamptz, ip text)
```

## 4. API design (FastAPI, `/api/v1`)

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/signup`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me` |
| Orgs/Projects | `GET/POST /organizations`, `GET/POST /projects`, `GET /projects/{id}` |
| Integrations | `POST /integrations/{provider}/connect` (stores encrypted key), `DELETE …/disconnect`, `POST /integrations/csv/upload` (multipart + column map), `GET /integrations/status` |
| Event ingest | `POST /ingest/events` (project API key, batch of usage events) |
| Costs | `GET /costs/summary` (KPIs: this/last month, Δ%, projected), `GET /costs/timeseries` (granularity day/week/month), `GET /costs/breakdown?by=provider\|model\|application\|tenant\|environment` |
| Anomalies | `GET /anomalies`, `POST /anomalies/{id}/dismiss`, `POST /anomalies/scan` (on-demand) |
| Investigate | `POST /investigate` `{project_id, period, anomaly_id?}` → root cause, evidence, action, savings, confidence |
| Recommendations | `GET /recommendations`, `POST /recommendations/{id}/dismiss` |
| Alerts | `GET/POST /alerts`, `POST /alerts/{id}/test` |
| Demo | `POST /demo/seed` (labeled synthetic org), `DELETE /demo/reset` |

Auth: short-lived JWT access + rotating refresh; project ingest keys are
random 48-char strings, stored as SHA-256 hash, shown once.

## 5. Provider integration strategy

- **Day 1:** OpenAI + Anthropic read-only keys, least privilege. Anthropic
  needs a *separate admin key* — the connect UI collects org key + admin key
  and labels what each is for. Sync worker pulls daily (usage/cost APIs lag
  minutes–hours; we show "data as of" timestamps, never imply real-time).
- **CSV:** guided mapping UI; validate required columns; dry-run preview
  showing parsed rows + computed cost before commit.
- **Event API:** tiny SDK-optional — plain HTTPS POST works from any stack;
  document the 8-field minimal payload. This is the strategic source: it's
  what carries `tenant_id`/`application` for the margin-analysis spearhead.
- **Secrets:** Fernet envelope encryption (data key per org, master key from
  env/KMS); `key_last4` only for display; rotation endpoint; every
  credential use written to `audit_log`.
- **Trust:** "Bill reconciliation" view compares provider-reported cost vs
  our calculated cost per day and flags drift > 5% (addresses the data-trust
  gap found in research — LiteLLM race conditions, Portkey cache-token bug).

## 6. Cost calculation model

- `costing.py` is the single place prices turn into dollars. Nothing else
  hardcodes a price.
- Per event: `input_tokens/1M × input_price + output_tokens/1M × output_price
  (+ cached/reasoning variants)` using the price row effective at
  `occurred_at`. Stored on the event at ingest; recomputable via backfill
  when the catalog changes.
- UI labels, always: **Reported** (provider's number) · **Calculated**
  (our catalog math) · **Estimated** (modeled/forecast). Never mix them
  silently.
- Pricing catalog seeded from a versioned JSON file (curated from provider
  pages; Portkey's OSS catalog as cross-check), admin-refreshable.

## 7. Anomaly detection (deterministic — no LLM)

Nightly per (org, project), plus on-demand scan:

1. Build daily-cost series for the overall project and each dimension value
   (provider, model, application, tenant) with ≥ 14 days history.
2. `baseline = median(prior 28d)`, `recent = mean(last 7d)`; robust spread via
   MAD. Flag when `recent > baseline + max(3×MAD, $25 floor)` **and**
   `pct_change > 30%` **and** `abs_delta > $25` (tunable per org).
3. Attribute: decompose the delta into contributing sub-dimensions
   (e.g. overall +$1,200 → Customer Support Agent +$980, of which
   gpt-4.1 +$940) → stored as `evidence` JSON.
4. Also flag: first-seen expensive model, cost/request drift, single-tenant
   concentration (>50% of project spend), errored-request cost.
5. Severity from abs dollars + pct; alerts fire per `alerts` config.

## 8. Recommendation engine + Investigate

**Rules (deterministic)** produce candidates with dollar math:
- `model_routing`: (app, model) pairs over $100/mo where a cheaper same-tier
  model exists in the catalog → savings = Δprice × tokens × assumed 50%
  shiftable share. Confidence from volume + tier similarity.
- `prompt_caching`: repeated input prefixes (from event metadata when
  available) → savings from cached-input price delta. Without prompt text,
  downgraded to Low confidence with "connect event API" guidance.
- `token_hygiene`: output/input ratio outliers, excessive error spend.
- Each: current cost/mo, estimated savings/mo (labeled **estimate**),
  confidence, and a qualitative quality-risk note (v0.1; replay-based
  risk scoring in v0.2).

**Investigate flow:** user clicks "Why did spend increase?" (or an anomaly) →
backend gathers computed facts (deltas, contributions, top drivers) →
`narrator.py` sends *numbers* to a cheap LLM which returns *prose*
(root-cause story, evidence bullets, recommended action). The LLM never
computes; if it emits a number not in the input facts, the response is
rejected and retried once, then falls back to the template narrative.

## 9. Security model

- TLS everywhere; bcrypt passwords; JWT rotation; per-project ingest keys.
- Provider secrets encrypted at rest (envelope, KMS-managed master key in
  prod); least-privilege read-only keys; audit log on all credential
  operations and data exports.
- Tenant isolation: `org_id` on every row + Postgres RLS as defense in
  depth; no cross-org queries possible from the app role.
- Data retention controls per org (30/90/365 days, then hard delete);
  demo data is namespaced and labeled, never mixed with real data.
- No SOC 2 / GDPR / HIPAA claims until implemented and verified.

## 10. Deployment

- `docker-compose.yml`: `web` (Next.js), `api` (FastAPI), `worker`
  (same image, scheduler entrypoint), `postgres:16`. One command to run
  locally; same compose shape on AWS (ECS or a single EC2) for early prod.
- Migrations via Alembic, run at deploy. Backups: nightly pg_dump to
  object storage (prod). Health endpoints + structured logs from day one.
- Frontend talks to the API via `NEXT_PUBLIC_API_URL`; no secrets in the
  browser bundle.

## 11. Testing strategy

- `costing.py`: property tests (price × tokens math, effective-date
  boundaries, reported-vs-calculated labeling).
- Anomaly detection: synthetic fixtures (spike, drift, no-op) with asserted
  outcomes — the same fixtures power demo mode.
- API: integration tests with throwaway Postgres per run.
- Frontend: smoke tests on the onboarding → dashboard path.
- Every phase ends with the compose stack green and the demo flow working.
