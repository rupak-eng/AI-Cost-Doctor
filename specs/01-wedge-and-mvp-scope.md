# Wedge Decision & MVP Scope

**Date:** 2026-09-21
**Basis:** `research/competitor-analysis.md` (Phase 0, ~30 products researched with live verification)

## Research verdict (one paragraph)

The "diagnosis gap" is real and nearly unoccupied: only PromptLayer's Runtime
Intelligence (scoped to its own prompt-ops instrumentation) and Provara (scoped
to its own gateway) ship automated cost-change diagnosis with dollar-quantified
savings — everything else shows cost as a number and leaves the investigation
to the user. **Nobody computes per-customer/tenant AI unit economics**
("which customer is unprofitable?"), the most-quoted unmet founder need.
The enterprise slot is taken (CloudZero, Finout — sales-led, ~$1k+/mo);
the startup self-serve slot ($49–$399/mo) is open. Pure cost tracking doesn't
sustain a business (Murnitur dead, Lytix pivoted away from cost) — diagnosis
tied to measurable savings is the viable wedge. Timing helps: Helicone entered
maintenance mode (Mar 2026), stranding a cost-conscious proxy user base.

## Decision

**Revised product hierarchy (2026-09-21, approved with adjustment):**

1. **Per-customer AI unit economics / Tenant P&L — the spearhead.**
   "Which of my customers are unprofitable because of AI usage?" then
   "Why, and what can I change to fix it?"
2. **Cost diagnosis — the core engine.** Anomaly → root-cause attribution
   across provider/model/application/tenant.
3. **Savings recommendations — monetization / value proof.**
   Dollar-quantified, confidence-labeled, never guaranteed.
4. **General cost analytics — supporting feature.** The dashboard exists to
   serve the diagnosis loop, not as the product's identity.

Do NOT position AI Cost Doctor primarily as an AI observability dashboard.
Lead with "AI unit economics", "customer profitability", "margin killers",
"cost diagnosis", "potential savings", "root cause". Never "LLM
observability platform", "AI monitoring platform", or "another dashboard".

**Wedge A — vendor-neutral cost-diagnosis layer — as the product,
Wedge B — per-customer/tenant margin analysis — as the spearhead feature
and lead go-to-market motion.**

- The product ingests from anywhere (provider billing APIs, CSV, proxy spend
  logs, event API) with zero code changes and no gateway to adopt.
- Core loop: anomaly detection → "Investigate" root-cause narrative →
  dollar-quantified savings recommendations → Slack/email alerts.
- Lead GTM story for B2B AI SaaS: "we found your unprofitable customers
  and $X/mo in savings." Highest willingness to pay, clearest pain,
  differentiates against PromptLayer (no tenant P&L) and every observability tool.
- Wedge C (Bedrock-specific) becomes an expansion feature, not the company bet.

**What would invalidate this:** PromptLayer ships cross-provider ingest +
tenant P&L before we reach traction, or OpenAI/Anthropic ship genuinely good
native cost diagnosis (structural disincentive: neither will ever show the
other's spend). Revisit quarterly against the watchlist in the research report.

## MVP scope (v0.1) — in (demo-first order)

0. **Demo-first development:** alongside landing/auth, ship a polished
   interactive demo on clearly-labeled synthetic data ("Demo data").
   Every demo metric is computed by the real cost engine over seeded usage
   events — no hardcoded P&L figures, no faked economics. The same backend
   calculations power demo mode and real customer data.
1. **Tenant P&L (spearhead):** cost per customer/tenant, margin vs monthly
   revenue, margin-killer list and alerts.
2. **Cost diagnosis engine:** deterministic anomaly detection →
   "Investigate" root-cause narrative (model, application, volume vs token
   change, expensive workflows) → evidence → recommended action →
   estimated savings → confidence.
3. **Savings recommendations:** model routing, prompt caching, token
   hygiene — each with current cost, estimated monthly savings (labeled as
   estimates, never guaranteed), confidence.
2. **Onboarding (5-minute path):** connect OpenAI (Costs/usage API), connect
   Anthropic (Admin Usage + Cost APIs), CSV upload with column mapping,
   per-project event-ingest API keys (`POST /api/v1/ingest/events`).
3. **Pricing catalog + deterministic cost engine:** versioned provider→model
   prices with effective dates; per-event computed cost; reported vs
   calculated vs estimated cost distinguished in the UI.
4. **Dashboard + cost explorer (supporting):** total spend, this/last month,
   Δ%, projected month-end, requests, tokens, avg cost/request, breakdowns
   by provider/model/application/tenant, spend over time; filters +
   CSV export. In service of the diagnosis loop, not the product identity.
5. **Landing page:** per the brief (problem, how it works, diagnosis
   example, savings, providers, security, pricing, FAQ) — hero "Find where
   your AI budget is leaking.", CTAs "Analyze My AI Spend" → signup and
   "See How It Works" → demo. No unbacked claims.

## MVP success criteria (demo-first)

- **Demo flow:** landing → demo → customer P&L → margin killer →
  investigate → root cause → recommended action → estimated savings,
  all on labeled synthetic data computed by the real engine.
- **CSV flow:** the same flow working with uploaded CSV data.
- Signup → connected data → P&L with diagnosis in under 5 minutes.
- Investigate produces the correct root cause on synthetic spike fixtures.
- Quantified savings shown ≥ 10× the subscription price (retention bar).
- First 10 design-partner conversations booked from the landing page.

## Explicitly out of scope (v0.1)

- Native Bedrock connector (CSV/event ingest only in v0.1; CloudWatch +
  inference-profile connector in v0.2).
- OTel span ingest (v0.2; event API covers the metadata need for the wedge).
- Real billing — landing page shows pricing; Stripe subscription billing is
  Phase 7.
- Replay-based quality-risk scoring for model-swap recommendations
  (PromptLayer's edge). v0.1 shows a qualitative risk note + confidence;
  replay harness in v0.2.
- Mac companion app (Phase 8).
- SOC 2 / GDPR / enterprise compliance claims.

## Pricing hypothesis (to validate against competitors in research)

Free (1 project, basic analytics) → **$49/mo** Starter (1 project, anomaly
detection, savings recs) → **$149/mo** Growth (multi-project, tenant P&L,
team access, history) → **$399/mo** Scale (multi-team, advanced
integrations, retention/support). No per-seat tax, no per-event tax —
priced as a small fraction of AI spend (~1–10% at $5k/mo bill, in line
with FinOps norms).

## MVP success criteria (demo-first)

- **Demo flow:** landing → demo → customer P&L → margin killer →
  investigate → root cause → recommended action → estimated savings,
  all on labeled synthetic data computed by the real engine.
- **CSV flow:** the same flow working with uploaded CSV data.
- Signup → connected data → P&L with diagnosis in under 5 minutes.
- Investigate produces the correct root cause on synthetic spike fixtures.
- Quantified savings shown ≥ 10× the subscription price (retention bar).
- First 10 design-partner conversations booked from the landing page.
