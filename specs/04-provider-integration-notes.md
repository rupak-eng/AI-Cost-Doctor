# Phase 4 — Provider integration notes (OpenAI + Anthropic)

**Researched:** 2026-09-21 (all URLs fetched live this date)
**Author:** Phase 4 builder
**Status:** findings below drove the connector implementation in `app/backend/app/services/providers/`

> Rule: anything not confirmed by the primary docs is marked **[uncertain]**.
> We build only what the docs support. We do not invent endpoints, fields, or
> attribution the providers don't offer.

---

## 1. OpenAI

### Primary sources
- API reference (Usage): https://platform.openai.com/docs/api-reference/usage
- Cookbook (official, with real request/response examples):
  https://cookbook.openai.com/examples/completions_usage_api
- API overview (authentication): https://platform.openai.com/docs/api-reference/debugging-requests
  (auth section; full overview at the API reference root)

### Authentication
- **Admin API key only.** `Authorization: Bearer <OPENAI_ADMIN_KEY>`.
- Admin keys are created at
  `https://platform.openai.com/settings/organization/admin-keys` (per the
  official cookbook). Regular project / user API keys return **403** on the
  organization usage/cost endpoints.
- Optional scoping headers: `OpenAI-Organization`, `OpenAI-Project`.

### Usage endpoint (tokens)
- `GET https://api.openai.com/v1/organization/usage/completions`
- Query params (confirmed by cookbook):
  - `start_time` (required): Unix seconds, inclusive
  - `end_time`: Unix seconds, exclusive
  - `bucket_width`: `"1m"`, `"1h"`, or `"1d"` (default `"1d"`)
  - Filters: `project_ids[]`, `user_ids[]`, `api_key_ids[]`, `models[]`, `batch`
  - `group_by[]`: `model`, `project_id`, `user_id`, `api_key_id`, `batch`,
    `service_tier`
  - `limit` (buckets per page), `page` (cursor)
- Pagination: `has_more` + `next_page`.
- Response shape (confirmed by cookbook example):
  `data[]` → `{object:"bucket", start_time, end_time, results[]}` where each
  result has `object:"organization.usage.completions.result"` plus
  `input_tokens` (includes cached), `output_tokens`, `num_model_requests`,
  `input_cached_tokens`, `input_audio_tokens`, `output_audio_tokens`, and the
  grouped dimensions (`model`, `project_id`, `user_id`, `api_key_id`, `batch`)
  when `group_by` is supplied (null otherwise).

### Costs endpoint (USD)
- `GET https://api.openai.com/v1/organization/costs`
- `bucket_width`: **`"1d"` only** (confirmed by the API reference text:
  "Currently only `1d` is supported").
- `group_by`: `project_id`, `line_item` **[uncertain: one third-party source
  mirroring a 2026 SDK spec also lists `api_key_id`; not confirmed in the
  official reference text we extracted — we do not rely on it]**.
- `limit`: 1–180, default 7. Pagination via `has_more`/`next_page`.
- Response result: `{object:"organization.costs.result", amount:{currency, value},
  line_item?, project_id?}`.

### Granularity / latency / limits (what this means for us)
- **Best granularity: per-model token buckets (daily; hourly available).**
  There is **no per-request feed** and **no per-customer/tenant dimension**.
  The closest attribution proxy is `group_by=api_key_id` (or `user_id`).
- **The costs endpoint cannot be joined to model-level usage**: it groups by
  `line_item`, not by model. Allocating reported dollars to models would be
  invented — we keep reported cost rows separate from token rows and never
  allocate.
- Data freshness: not precisely documented; daily buckets observed < 24h
  **[uncertain — not stated in docs]**.
- Historical depth: not documented as a hard cap in the extracted reference
  **[uncertain]**; we page backwards in 30-day windows and stop on empty data.

---

## 2. Anthropic

### Primary sources
- Overview: https://docs.anthropic.com/en/api/usage-cost-api
- Usage API reference:
  https://docs.anthropic.com/en/api/admin-api/usage-cost/get-messages-usage-report
- Cost API reference:
  https://docs.anthropic.com/en/api/admin-api/usage-cost/get-cost-report

### Authentication
- **Admin API key** (`sk-ant-admin01-…`), created in Console → Organization
  Settings → Admin Keys. Sent as `x-api-key` header plus
  `anthropic-version: 2023-06-01`. Regular workspace keys return 403.
- **Claude Enterprise (claude.ai) organizations have no Admin API keys** and
  must use the separate Claude Enterprise Analytics API — out of scope for
  Phase 4 (documented at the same overview page).

### Usage endpoint (tokens)
- `GET https://api.anthropic.com/v1/organizations/usage_report/messages`
- `starting_at` (required, RFC 3339), `ending_at` (RFC 3339).
- `bucket_width`: `"1m"`, `"1h"`, `"1d"` (default `"1d"`).
- `group_by[]`: `account_id`, `api_key_id`, `context_window`, `inference_geo`,
  `model`, `service_account_id`, `service_tier`, `speed`, `workspace_id`
  (`speed` needs the `fast-mode-2026-02-01` beta header — we don't use it).
- Filters: `api_key_ids[]`, `workspace_ids[]`, `models[]`, `service_tiers[]`
  (`batch|flex|flex_discount|priority|priority_on_demand|standard`),
  `context_window[]`, `inference_geos[]`, `speeds[]`, `account_ids[]`,
  `service_account_ids[]`.
- Bucket limits: `1d` default 7 / max 31; `1h` default 24 / max 168;
  `1m` default 60 / max 1440. Pagination via `has_more`/`next_page`.
- Token detail (per the overview page): uncached input, cached input
  (cache read), cache creation, and output tokens, plus server-tool use.
  **[uncertain: exact JSON field names of the results objects were not present
  in the extracted reference text; the connector parses defensively and keeps
  the raw result in `meta.provider_raw`.]**

### Cost endpoint (USD)
- `GET https://api.anthropic.com/v1/organizations/cost_report`
- `bucket_width`: **`"1d"` only** (default `1d`). `limit` default 7 / max 31.
- `group_by`: `description`, `workspace_id`. When grouping by `description`,
  responses include parsed fields such as `model` and `inference_geo`.
- Costs are **decimal strings in USD cents** (lowest currency unit).
- Covers token, web search, and code execution costs. **Priority Tier costs are
  NOT included** (track via the usage endpoint's `service_tier=priority`).
  Code execution costs appear **only** here, not in the usage endpoint.
- Pagination via `has_more`/`next_page`.

### Freshness / polling (documented)
- Data typically appears **within 5 minutes** of request completion.
- Polling **once per minute sustained** is supported; bursts OK for pagination.

### Granularity / limits (what this means for us)
- **Best granularity: per-model (+ workspace/api-key/service-tier) token
  buckets.** No per-request feed, no per-customer dimension. `api_key_id` /
  `workspace_id` are the closest attribution proxies.
- The cost report's `description` grouping *may* carry a parsed `model`, but
  the description string format is not contractually stable — we store cost
  rows keyed by description verbatim and do **not** parse models out of them.

---

## 3. What we built (and deliberately did not)

### Built
- Encrypted provider credentials (`provider_credentials` table, existing
  envelope-encryption pattern): OpenAI Admin key, Anthropic Admin key.
  Key validation on connect via a cheap 1-bucket API call; provider error
  surfaced, key never logged.
- Sync jobs (manual trigger in Phase 4; scheduled later):
  - OpenAI: `usage/completions` grouped by `model`, daily buckets →
    `usage_events` rows (source `openai`) with tokens + **calculated** cost
    from our catalog (deterministic). `cost_reported_usd` stays NULL at this
    granularity because the provider does not report per-model cost.
  - OpenAI: `costs` grouped by `line_item` → `provider_cost_reports` rows
    (reported USD, org level, never allocated to models).
  - Anthropic: `usage_report/messages` grouped by `model`, daily buckets →
    `usage_events` rows (source `anthropic`) with tokens + calculated cost.
  - Anthropic: `cost_report` → `provider_cost_reports` rows (reported USD).
- Optional `group_by` extension (`api_key_id` for OpenAI; `api_key_id` /
  `workspace_id` for Anthropic) stored in `meta` — raw material for a future
  key→tenant mapping UI. No tenant attribution is invented.
- Unpriced models (no catalog row) are stored with NULL calculated cost and
  surfaced in the sync summary — missing data, never invented prices.

### Deliberately NOT built
- Per-tenant/customer attribution from provider APIs (not offered by either).
- Model-level allocation of reported costs (would be invented).
- Webhooks / real-time streaming (both APIs are poll-only).
- Claude Enterprise Analytics API (different product/key).
- Azure OpenAI and Bedrock/Vertex-hosted Claude (different billing systems).
- Automatic scheduling (Phase 6 will own the scheduler; Phase 4 sync is manual).
