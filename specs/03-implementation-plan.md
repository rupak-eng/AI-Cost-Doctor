# Implementation Plan

**Date:** 2026-09-21 · Maps to user brief Phases 0–8.
Phase 0 (research) and Phase 1 (this spec set) are done after wedge sign-off.

## Phase 2 — Landing page + authentication
- Next.js app shell, Tailwind, landing page per brief §"Landing page"
  (hero "Find where your AI budget is leaking.", problem, how-it-works,
  diagnosis example, savings, providers, security, pricing, FAQ).
  "Analyze My AI Spend" → signup; "See Demo" → demo mode.
- Auth: signup/login/JWT/refresh, org + first project creation,
  protected app shell. Empty-state dashboard.
- **Done when:** `docker compose up` serves landing + working signup →
  empty dashboard; no console errors.

## Phase 3 — Provider / CSV / event ingestion
- Encrypted credential store + OpenAI connector (Costs + usage APIs).
- Anthropic connector (Admin Usage + Cost APIs; dual-key onboarding UI).
- CSV upload with column mapping + dry-run preview.
- `POST /v1/ingest/events` + per-project API keys + minimal docs page.
- Sync worker (daily provider pull, "data as of" labeling).
- Pricing catalog seed (versioned JSON) + `costing.py` with tests.
- Bill-reconciliation view (reported vs calculated, drift flag).
- **Done when:** connecting OpenAI test key (or CSV fixture) yields correct
  per-event costs; reconciliation flags a doctored drift fixture.

## Phase 4 — Cost analytics
- Dashboard KPIs (this/last month, Δ%, projection, requests, tokens,
  avg $/request), timeseries, breakdowns (provider/model/app/tenant/env).
- Cost explorer with all filters + CSV export.
- Tenant P&L view (cost per tenant, margin vs plan price input, margin-killer
  list). Plan price captured per tenant via settings or event metadata.
- Demo-mode seeder with labeled synthetic data (includes a spike + a
  margin-killer tenant for the sales story).
- **Done when:** demo org shows the full dashboard; explorer filters compose;
  every number traceable to events.

## Phase 5 — Anomaly detection + alerts
- Nightly + on-demand scan per §7 of architecture; anomalies list with
  evidence; Slack + email alert channels; alert test button.
- **Done when:** synthetic spike/drift/no-op fixtures produce exactly the
  expected anomalies (asserted in tests), and a Slack test alert delivers.

## Phase 6 — AI diagnosis + recommendations
- Rules engine (§8): model routing, prompt caching, token hygiene —
  savings page with estimates + confidence, "estimates not guaranteed"
  labeling.
- Investigate flow: fact-gathering → LLM narrator → narrative UI with
  root cause / evidence / action / savings / confidence; template fallback.
- Wire anomaly → Investigate → recommendation into one click-path.
- **Done when:** on demo data, "Why did spend increase?" returns the
  correct driver, a sensible action, and dollar savings within 10% of the
  fixture's ground truth.

## Phase 7 — Pricing / billing
- Stripe: checkout, webhooks, plan gating (project count, history,
  seats→n/a), billing portal. Free/Starter/Growth/Scale per wedge doc.
- **Done when:** test-mode subscription upgrades/downgrades gate features
  correctly.

## Phase 8 — Mac companion app
- Menu-bar app (Swift/SwiftUI): today's spend + Δ%, top driver, spike
  notifications, "Investigate" deep link to web. Read-only API token.
- **Done when:** notarized build shows live data from the API.
- Explicitly last — web SaaS must be selling before this starts.

## Cross-phase rules
- End every phase with: compose stack green, migrations clean, demo flow
  working, docs updated.
- Never present demo/synthetic data as real; never present estimates as
  guaranteed; never invent an integration — if a provider API can't do it,
  CSV/event ingest is the honest fallback and the UI says so.
