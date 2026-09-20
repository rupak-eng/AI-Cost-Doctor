# AI Cost Doctor — Competitor Analysis

**Research date:** 2026-09-21
**Purpose:** Phase 0 market research for AI Cost Doctor, a B2B SaaS for actionable LLM/AI cost diagnosis. Target: US/UK AI startups and SaaS companies, seed–Series B, 5–100 developers, ~$500–$50,000+/mo in AI API spend.
**Core thesis under test:** the market needs "what should I do about my AI bill?" (actionable diagnosis), not another "what happened?" (generic observability).

**Method:** Four parallel research tracks with live web verification (pricing pages, docs, GitHub issues, Reddit, Hacker News, G2 reviews) conducted September 2026. Pricing and feature claims cite sources inline. Anything unverifiable is marked **[unverified]**. Competitor claims taken from vendor marketing are labeled as such.

---

## Executive Summary

- **The "diagnosis gap" is real and nearly unoccupied.** Across ~30 products, only two ship anything resembling automated cost diagnosis: **PromptLayer's Runtime Intelligence** (spend-change narratives + model-swap recommendations with dollar savings and replay-based quality risk — but scoped to its own prompt-ops instrumentation) and **Provara** (OSS gateway with 7-vs-28-day anomaly detection and "quality-comparable savings recommendations" — but requires adopting its gateway). Everything else shows cost as a number and leaves the investigation to the user.
- **Per-customer/tenant unit economics ("which customer is unprofitable?") exists nowhere.** This is the most-quoted unmet need in founder anecdotes and the emptiest cell in the market.
- **The enterprise slot is taken; the startup self-serve slot is open.** CloudZero and Finout have the closest capabilities but are enterprise-priced (~$1,000+/mo, sales-led). Vantage is startup-priced but its LLM allocation is a private preview, daily-batch, OpenAI+Bedrock only.
- **High mortality among pure cost-tracking tools** (Murnitur likely dead, Lytix pivoted away from cost) proves that *tracking alone* doesn't sustain a business — diagnosis tied to measurable savings is the viable wedge.
- **Two near-term threats to watch:** PromptLayer (validates the concept, could broaden) and Provara (open-source, most direct feature overlap). A third structural threat: hyperscalers adding native diagnosis (Google's April 2026 FinOps AI Explainability Agent).
- **A gift:** Helicone entered maintenance mode in March 2026, stranding a cost-conscious proxy user base that is a natural migration audience.
- **Recommendation (see §8):** Build the vendor-neutral **diagnosis layer** — 5-minute connect (provider billing APIs + CSV + proxy/OTel log ingest), anomaly alerts with root-cause narratives, dollar-quantified savings recommendations, leading with **per-customer/tenant margin analysis** for B2B AI SaaS. No gateway to adopt, no re-instrumentation, no per-seat or per-event pricing tax. Price $49–$399/mo, self-serve.

---

## 1. LLM Observability Platforms (cost features)

These tools *see* every request and therefore compute cost — but cost is a column in their UI, not a product.

### 1.1 Langfuse (langfuse.com)

- **Cost features:** Every tier includes token and cost tracking — per-generation cost from a built-in model price list, cost dashboards filterable by user, session, trace name, model. Metric alerts exist (2 on Hobby, 20 on Core, 50 on Pro) but are generic, not cost-specific. No anomaly detection for spend, no budget caps, no savings recommendations. Acquired by ClickHouse in Jan 2026.
- **Pricing (verified live):** Hobby $0/mo (50k units/mo, 30-day data, 2 users); Core $29/mo (100k units/mo, 90 days, unlimited users); Pro $199/mo (100k units/mo, 3-year retention, SOC2/ISO27001); Enterprise $2,499/mo. Overages $8/100k units. Teams SSO/RBAC add-on $300/mo. Metering unit = trace/observation/score — an agentic request with 4 LLM calls + 2 eval scores costs 6 units. Self-host free (MIT). Source: https://langfuse.com/pricing
- **Target:** Framework-agnostic engineering teams wanting deep OSS LLM observability (tracing, prompts, evals).
- **Strengths:** Most complete OSS feature set; 21k+ GitHub stars; 50+ integrations + native OTel; best-in-class prompt versioning/A-B/playground; unlimited seats on paid tiers.
- **Weaknesses:** Multi-agent trace fragmentation bugs; self-hosting ops burden; $300/mo SSO add-on prices out small teams; unit billing balloons with agentic workloads.
- **Complaints:** Unit-based billing surprises for agent workflows; self-hosted ClickHouse/Postgres burden; no trigger-experiment REST API (GitHub discussions #9131, #4587).
- **Diagnosis gaps:** No root-cause of cost changes, no savings recommendations, no dollar-impact estimates, no per-tenant attribution beyond manual tags. Cost is visible, never interpreted.
- **Differentiation:** Langfuse exports + OTel are an ideal *data feed* — AI Cost Doctor can ingest without re-instrumentation and deliver the diagnosis Langfuse never will.

### 1.2 LangSmith (LangChain)

- **Cost features:** Token-usage dashboard (tokens by day/week/month, by model, avg tokens/run, input vs output, histograms). A cost-tracking doc exists (https://docs.langchain.com/langsmith/cost-tracking) and newer Fleet pages advertise cost alerting — but cost is raw material the user converts to dollars. No recommendations, no anomaly explanations, no budget caps.
- **Pricing:** Developer free (5k traces/mo, 1 seat, 14-day retention); Plus $39/seat/mo (10k traces/mo; overages reported $0.50/1k traces at 14-day, $5/1k at 400-day — **[unverified]** which tier structure is current; one Sep 2026 analysis showed a different structure); Enterprise custom (~$100k+/yr reported at scale **[unverified]**). Source: https://www.langchain.com/langsmith/pricing
- **Target:** Teams committed to the LangChain/LangGraph stack.
- **Strengths:** Framework-native traces (each LangGraph node traceable); best agent trajectory views; SOC 2 Type II, HIPAA, GDPR; hybrid/self-host on Enterprise.
- **Weaknesses:** Per-seat pricing punishes growing teams ($975/mo for 25 engineers before overages); no OSS self-host; weaker outside LangChain; lock-in.
- **Complaints:** Per-seat pricing is the recurring grievance; multi-agent tracing fragments on sub-agent handoffs; "expensive at scale" consensus.
- **Diagnosis gaps:** Token histograms, not cost stories. No change attribution, no recommendations, no dollar modeling, no per-tenant breakdowns.
- **Differentiation:** LangSmith's own per-seat bill is a pain point — a diagnosis product priced as a fraction of *LLM spend* (not per seat) and stack-agnostic is an easy second-dashboard sell.

### 1.3 Braintrust (braintrust.dev)

- **Cost features:** "Granular cost analytics" — LLM cost per request, user, and feature; pinpoints which prompts/tool calls drive spend. Ships an AI gateway/proxy with semantic caching, rate limiting, model routing (cost *reduction* levers). Raised $80M Series B at $800M valuation (Feb 2026).
- **Pricing:** Starter free (1M spans/mo, 14-day retention, unlimited users); Pro $249/mo (unlimited spans, 30-day retention); Enterprise custom. Overages $3/GB, $1.50/1k scores. Source: https://www.braintrust.dev/docs/guides/pricing
- **Target:** Evaluation-driven teams where output quality is non-negotiable; strong in coding-agent workflows.
- **Strengths:** Tightest eval↔observability integration; "Loop" AI assistant; IDE-native via MCP; hybrid deployment; CI quality gating.
- **Weaknesses:** Highest entry price ($249/mo); GB+scores billing hard to forecast; eval-centric learning curve; no full self-host.
- **Complaints:** Storage-based pricing "not as intuitive as per-trace pricing" (https://techsy.io/en/blog/best-ai-observability-platforms); premium pricing "justified only for large teams."
- **Diagnosis gaps:** Shows cost per request/user/feature but never explains *why* costs moved; no cheaper-model-swap recommendations with quality-risk quantification; no budget alerts.
- **Differentiation:** Braintrust owns cost × quality data per trace but never computes **cost-per-quality** ("model X is 3× cheaper at equal quality score") — a natural AI Cost Doctor wedge on top of their data.

### 1.4 Helicone (helicone.ai)

- **Cost features:** Among the strongest here: automatic cost tracking across 300+ models, **cost-based rate limiting** (e.g., $5/hr/user via headers), response caching claiming 20–30% savings, cost/error threshold alerts via email/Slack, segmentation by user/org/custom property. Proxy architecture, 5-minute integration.
- **Pricing:** Hobby $0 (10k req/mo, 7-day retention); Pro $79/mo (unlimited seats, alerts, reports); Team $799/mo (5 orgs, SOC2/HIPAA); Enterprise custom. Startup program: 50% off year one (<$5M funded). Source: https://helicone.ai/pricing
- **Target:** Indie devs and small teams wanting drop-in logging/cost tracking.
- **Strengths:** Rust proxy (<5ms); one-line integration; 2.1B+ requests logged; caching+routing+rate-limiting = real optimization; unlimited seats at Pro.
- **Weaknesses:** Proxy-only visibility (no agent tracing depth); no eval framework; brutal Pro→Team jump ($79→$799).
- **Complaints:** **The dominant complaint is existential: Helicone entered maintenance mode on 3 March 2026 as the founding team joined Mintlify** — services live but no new features; procurement advice is to plan migration within 6–12 months (https://agentmodeai.com/agent-observability-langfuse-arize-helicone-langsmith/). Pre-existing: "$79/mo for a tool not shipping features"; "LLM API prices dropped ~80% since early 2025, monitoring costs haven't followed."
- **Diagnosis gaps:** Dashboards and hard rate limits, but no root-cause analysis, no model-swap recommendations, no dollar-impact of cache policies.
- **Differentiation:** **The single biggest tactical opportunity in this group:** Helicone's maintenance mode strands thousands of cost-conscious proxy users — a cost-first, actively-developed alternative is a natural migration target, especially one adding the diagnosis layer Helicone never had.

### 1.5 Portkey — observability side (portkey.ai)

(Cross-listed with gateways; cost-governance details in §2.2.)
- **Cost features:** Budget limits and usage policies enforced at ingress; real-time cost/latency/usage metrics; per-prompt observability with cost attribution (prompt, response, cache hit/miss, fallback decisions, cost per request); semantic caching; open-source model pricing catalog. **In March 2026 Portkey open-sourced the full gateway (Gateway 2.0, Apache 2.0)** — previously SaaS-only budget limits, semantic caching, and the pricing catalog are now free to self-hosters.
- **Pricing:** Developer free (10k logs/mo); Production $49/mo (100k logs/mo, semantic caching, guardrails); overage $9/100k requests to 3M/mo; Enterprise custom. Source: https://portkey.ai/pricing
- **Target:** Teams needing AI-native gateway governance; enterprise AI governance buyers.
- **Strengths:** 1,600+ models behind one API; composable fallbacks; semantic guardrails; MCP Gateway; AWS Marketplace; OSS eliminates lock-in anxiety.
- **Weaknesses:** Gateway in request path = latency dependency; log-metered pricing punishes scale; observability tied to gateway adoption.
- **Complaints:** Few public grievances; LiteLLM comparisons note managed pricing runs ~1–3% of LLM spend, steep vs self-hosting LiteLLM (https://particula.tech/blog/ai-gateway-decision-litellm-portkey-kong-ai-gateway). Note: a stale aggregator still shows old $99/mo Business tier — current is $49/mo Production.
- **Diagnosis gaps:** *Enforces* budgets but never *diagnoses* — stops overspend without telling you which workflow to fix or what the fix is worth.
- **Differentiation:** "You enforce budgets with Portkey; we tell you how to stay under them" — the analytical brain on top of Portkey's per-prompt cost traces.

### 1.6 PromptLayer (promptlayer.com) — ⚠️ closest direct competitor

- **Cost features:** The new **"Runtime Intelligence"** page (https://promptlayer.app/) shows exactly the AI Cost Doctor target feature set: estimated spend dashboard with MoM comparison ("$1,284.50, +18.2% vs $1,086.30 previous 30 days"); **"Why spend changed last 30 days" root-cause narratives** ("Spend rose +18% — almost entirely from the draft_reply workflow; impact +$198/mo; driver: gpt-4.1; 105 executions"); top spend drivers with MoM deltas; spend-by-feature attribution; **actionable recommendations with dollar savings** ("switch model from gpt-4.1 to gpt-5-nano; −68% cost; save $134/mo; risk: Low; similar token profile; 92% output overlap on replay") plus data-confidence scoring. Also per-request cost/latency and live model-comparison tables.
- **Pricing:** Free (2,500 req/mo, 5 users, 1 workspace); Pro $49/mo (+$0.003/transaction pay-as-you-go); Team $500/mo (25 users, 100k+ requests); Enterprise custom. SOC 2 Type II, HIPAA, GDPR. Source: https://promptlayer.com/pricing
- **Target:** Prompt-ops-centric engineering teams and PMs — "industrializing prompt quality."
- **Strengths:** Best-in-class prompt versioning (git-style diffs, no-code CMS); live model-comparison tables; release-label A/B tests on live traffic; **the only product in this group shipping automated savings recommendations with quantified dollars and replay-based quality-risk assessment.**
- **Weaknesses:** No routing gateway (SDK wrapper only); flat per-call logs by default (weaker agent visibility); $0.003/transaction adds up at scale; Team $500/mo steep for seed startups; prompt-ops focus, not general LLM infra.
- **Complaints:** Tight free tier; per-transaction pricing unpredictability; "focused on prompt ops, not general application hosting" (https://aitools.fyi/promptlayer). Quiet community footprint — no major Reddit/HN complaint threads found.
- **Diagnosis gaps (relative):** Scoped to prompt/model-switch optimization *within PromptLayer-instrumented calls* — no cross-provider bill reconciliation, no tenant-level unit economics, no caching/routing ROI quantification, no alert-driven diagnosis workflows.
- **Differentiation:** PromptLayer **validates the "cost doctor" concept** — and the gap is breadth and independence: a vendor-neutral diagnosis layer covering any provider/gateway, tenant-level P&L, and caching/routing ROI — the CFO-facing complement to PromptLayer's engineer-facing prompt ops. Watch them closely; they are the most likely incumbent to broaden into this space.

### 1.7 LangWatch (langwatch.ai)

- **Cost features:** Per-trace token usage, latency, and **cost attributed by user, feature, model, experiment**; live dashboard with **anomaly alerts**; Enterprise org-wide governance (spend by team, top spenders); thorough model price catalog (incl. audio TTS/STT); virtual-key budgets; natural-language trace queries ("which traces cost the most this week").
- **Pricing (verified):** Developer free; Growth €29/core-seat/mo + €5/100k events beyond 200k/mo (+€3/GB beyond 30-day retention); Enterprise custom (incl. cloud marketplace billing). Self-host via Docker Compose (Apache-2.0). Source: https://langwatch.ai/pricing
- **Target:** EU-rooted teams wanting OTel-native monitoring+evals; enterprises needing guardrails/self-hosting (Deloitte, Backbase cited).
- **Strengths:** OTel-native (no proxy, no lock-in); multi-agent topology views; monitoring→simulation→CI-gate "proof loop"; PII/prompt-injection guardrails; per-agent cost breakdowns.
- **Weaknesses:** Smaller ecosystem (4k+ GitHub stars); complex seat+usage pricing; weak US/UK startup brand.
- **Complaints:** None meaningful found — small community footprint.
- **Diagnosis gaps:** Attribution + anomaly alerts exist, but no root-cause narratives, no model-swap/savings recommendations with dollar impact, no tenant unit-economics beyond top-spender lists.
- **Differentiation:** Their OTel-native per-agent cost data is a great feed; the missing piece is "your anomaly traced to these 3 traces; fix = X; savings = $Y/mo."

### 1.8 Arize AI / Phoenix (arize.com)

- **Cost features:** Per-span token counts and USD cost via OpenTelemetry; Phoenix is the OSS trace/eval UI; Arize AX adds production monitoring, drift detection, alerting. Cost is a span attribute — no cost-diagnosis product layer. **Note: Arize was acquired by Dynatrace in Aug 2026** — roadmap now sits inside a large APM vendor.
- **Pricing:** Phoenix OSS free (Elastic License 2.0 — not OSI open-source); AX Free 25k spans/mo; AX Pro $50/mo; Enterprise custom (~$50–100k/yr reported **[unverified]**). Source: https://arize.com/pricing
- **Target:** ML-native/enterprise teams with OTel infrastructure.
- **Strengths:** Best OTel-native agent trace visualization; ML-ops heritage (drift/bias detection); deepest framework support; strong compliance; named enterprise customers.
- **Weaknesses:** Steep learning curve ("interface assumes engineering fluency," https://www.voiceflow.com/blog/what-is-arize-ai); ML-ops oriented; OSS lacks production alerting; Dynatrace acquisition = roadmap uncertainty.
- **Complaints:** Complexity; Elastic License gripes; enterprise pricing opacity.
- **Diagnosis gaps:** Cost is an attribute, not a surface — no cost dashboards with narratives, no anomaly explanations, no recommendations, no budgets.
- **Differentiation:** A simple, startup-priced, cost-first product with zero OTel complexity — explicitly not an ML-ops platform.

### 1.9 W&B Weave (Weights & Biases)

- **Cost features:** "LLM cost estimator" (token usage → cost/user spend); evaluations scored across dimensions including cost; per-call tokens/latency in traces. Attribution largely **manual tagging** (http://prefactor.tech/compare/prefactor-vs-wandb-weave).
- **Pricing:** Free tier; Team ~$50/user/mo; Enterprise custom (~$315–400/seat reported **[unverified]**). Source: https://wandb.ai/site/pricing. CoreWeave acquired W&B for $1.7B (2025) — roadmap skews toward GPU-cloud attach.
- **Target:** Teams already on W&B for ML experiment tracking; research orgs.
- **Strengths:** Natural extension for the W&B base; research-grade evals; experiment visualization; strong Bedrock/AWS integration; lineage linking.
- **Weaknesses:** Per-seat pricing punishing for 5–100 dev segment; coupled to W&B platform; dense UI; roadmap risk under CoreWeave.
- **Complaints:** Per-seat pricing is the #1 grievance; restrictive free tier; data-residency concerns.
- **Diagnosis gaps:** Estimation without attribution automation, anomaly detection, recommendations, savings quantification, or tenant views. Cost is an eval dimension, not a diagnosis surface.
- **Differentiation:** "Cost per experiment" and "cost-per-quality" analysis as the missing financial layer for W&B-native teams — without competing on tracing.

### 1.10 OpenLLMetry (Traceloop)

- **Cost features:** Essentially none — it's an **instrumentation library**, wrapping calls in OTel spans with standard `gen_ai.usage` token attributes. Cost calculation is explicitly DIY ("cost calculation is not part of the OTEL spec, you calculate it yourself"). Per-tenant attribution not in the base spec. Managed Traceloop platform exists but **pricing could not be verified** (no public pricing page).
- **Pricing:** OSS free (Apache 2.0).
- **Target:** Teams with existing OTel infrastructure wanting vendor-neutral instrumentation.
- **Strengths:** Zero lock-in; broadest provider/framework coverage of any instrumentation-only library; Python/TS/Go/Ruby SDKs; active development.
- **Weaknesses:** No UI/storage/query of its own; no evals; cost is your problem.
- **Complaints:** About what's missing, not what's broken — users end up building dashboards/cost logic themselves.
- **Diagnosis gaps:** Total.
- **Differentiation:** OpenLLMetry's ubiquity is an asset: support OTel-native ingestion (OpenInference/OpenLLMetry span formats) so teams instrument once and get diagnosis without adopting a new tracing vendor — the anti-lock-in wedge.

---

## 2. LLM Gateways / Proxies (cost angle)

Gateways sit in the request path, so they *control* spend (budgets, caching, routing) — but they optimize opaquely and never diagnose.

### 2.1 LiteLLM (BerriAI)

- **Cost features:** Per-request USD cost computed at call time against a built-in catalog (claims 140+ providers / 1,800+ models — vendor claim). Proxy admin UI: spend logs with per-request cost, cache-hit flags, aggregates by key/user/team/org/tag/agent. **Hard budget caps** per key/team/org/model with daily/monthly resets, soft-limit alerts, budget fallbacks (route to cheaper models when exceeded). Custom pricing overrides, provider discounts, internal markups for chargeback. Savings levers: lowest-cost routing, auto-routing, response + semantic caching, prompt compression.
- **Pricing:** OSS (MIT) free to self-host (~$200–500/mo typical infra **[third-party estimate]**). Enterprise has **no published price** — "priced on annual gateway request capacity, never per token" (https://www.beri.net/article/best-llm-gateways-multi-provider-cost-control-2026). Third parties cite Enterprise Basic ~$250/mo and Premium ~$30k/yr **[unverified]**.
- **Target:** Platform teams at large enterprises (NVIDIA, Netflix, Lemonade, IBM, Okta, SAP, AT&T, Twilio cited); self-hosters; dev teams routing IDE tools for per-person tracking.
- **Strengths:** Widest provider breadth; most configurable router (cost/latency/usage strategies, failover); no per-token markup (BYOK); day-zero model support; spend tracking at zero software cost.
- **Weaknesses:** You operate the stack (Postgres, Redis, K8s); Python runtime overhead (vendor benchmarks claim Kong/Portkey beat it on throughput — treat cautiously); feature-parity gaps for provider-native params.
- **Complaints (specific, sourced):**
  - **Security had a rough 2026:** compromised PyPI releases 1.82.7/1.82.8 ("TeamPCP" supply-chain campaign, Mar 2026); CVE-2026-42208 SQL injection in API-key verification **exploited ~26h after disclosure**, targeting the credentials table; privilege-escalation chain (CVE-2026-47101/47102, sandbox escape CVE-2026-40217) reaching master key/DB/provider keys (Obsidian Security); host-header auth bypass GHSA-4xpc-pv4p-pm3w (patched 1.84.0). Sources: https://gbhackers.com/critical-litellm-flaw/, https://github.com/mrepol742/melvinjonesrepol/blob/HEAD/src/content/blog/litellm-had-a-rough-year-and-your-proxy-might-be-next.mdx
  - **Budget accounting race condition** causing "financial tracking corruption" under concurrent load (https://github.com/emerzon/litellm/issues/15)
  - **Streaming usage loss:** aborted streams log failures *without computing usage* — "Provider bills for tokens, but LiteLLM cannot bill downstream customers" (issue #14457, open since Sep 2025)
  - **Latency overhead:** ~4.3s via proxy vs ~1.6s direct in one user report (https://github.com/BerriAI/litellm/discussions/4298)
- **Diagnosis gaps:** Tracks and enforces spend but never diagnoses: no root-cause of changes, no anomaly alerting beyond static thresholds, no proactive quantified savings recommendations; per-customer attribution only via manual keys/tags; cost accuracy itself shaky (above).
- **Differentiation:** LiteLLM's cost data lives in the customer's own Postgres/spend logs — a vendor-neutral diagnosis layer can read it without requiring a gateway switch, and add the missing anomaly detection, spike root-cause, and dollar-measured savings — plus reconcile tracked spend against actual provider bills.

### 2.2 Portkey — gateway side (portkey.ai)

- **Cost features:** "Portkey Models" open-source pricing DB (40+ providers) powering automatic per-request cost tracking; negotiated-rate overrides. Logs (every request, USD cost), Analytics tab (21+ metrics: total cost, cache hit rate, latency, error rate) drillable by tenant/model/time; metadata-tag cost tracking. Budget limits cost- or token-based (min $1), weekly/monthly resets, email thresholds, 429 hard-block — **but budget limits cannot be edited once set** (must duplicate). "Provider optimization" auto-switches to cheapest provider; semantic + simple caching (Production+). FinOps blog claims unusual-spending detection, forecasting, model comparisons, "budget optimization recommendations" — **reads as enterprise marketing; no self-serve UI evidence found [unverified]**.
- **Pricing (verified via multiple current sources):** Developer free (10k recorded logs/mo); Production **$49/mo** (100k recorded logs/mo, $9/additional 100k to 3M/mo, semantic caching, guardrails); Enterprise custom (~$2k–10k+/mo reported **[unverified]**). **Billing unit is recorded logs, not requests** — proxying unlimited on free; only logging stops. Source: https://portkey.ai/pricing
- **Target:** AI-native startups wanting one control plane; enterprises (Qoala, Haptik, Fortune 500 pharma cited).
- **Strengths:** 1,600+ models, 250+ providers; sub-1ms claimed latency; excellent observability; metadata FinOps; strong support reputation; genuinely useful free tier.
- **Weaknesses:** Log-metered pricing punishes keeping history (extrapolated ~$4,540/mo at 50M logs/mo **[extrapolation, not quoted]**); untracked-price models show "0 cents" and are **silently excluded from budget limits**; 30-day log retention on Production limits trend analysis.
- **Complaints:** G2: missing dashboard data export ("manual process adds friction"); UI flakiness/docs gaps; GitHub #855 fallback config bugs; **Bedrock cache-token double-counting cost bug** (PR #1211); SSRF CVE-2025-66405 (patched 1.14.0).
- **Diagnosis gaps:** No spike root-cause in self-serve; recommendations qualitative, never dollar-quantified; anomaly detection unverifiable; retention/pricing discourage keeping diagnosis history.
- **Differentiation:** Portkey emits OTel GenAI telemetry + CSV exports — a neutral layer ingests it and adds diagnosis, and works with the free OSS gateway logs, sidestepping the per-log meter.

### 2.3 OpenRouter

- **Cost angle:** Purest cost-routing play: one key, one bill, 500+ models across 80+ providers, provider rates at **0% markup**; monetization is a **5.5% platform fee on credit purchases** ($0.80 min), not on inference (https://openrouter.ai/blog/insights/openrouter-vs-litellm/). BYOK: 5% fee above free allowance ($25k/mo PAYG, $200k/mo Enterprise list-price inference **[per official FAQ, Aug 2026]**). Free tier: 13+ free models. Cost tools: unified analytics (spend/latency/errors per key); activity reporting by model/key/creator/workspace; `:floor` (cheapest) / `:nitro` (fastest) routing suffixes; auto failover. **Stripe acquired OpenRouter for $7B+ (Aug 2026)** — expect deeper billing integration. Breakeven vs self-hosted LiteLLM (~$200/mo infra): OpenRouter costs more once model spend passes ~$3,600/mo.
- **Pricing:** No subscription; prepaid credits (non-refundable); provider list prices + 5.5% credit fee. Enterprise custom.
- **Target:** Indie hackers, experimenters, AI startups needing instant model breadth (~10M users mid-2026). Weak enterprise governance.
- **Strengths:** Deepest catalog; transparent pricing; cheapest price/quality A/B; zero infra; strong docs/community.
- **Weaknesses:** 5.5% compounds ($6.6k/yr on $10k/mo); thin org features (no RBAC, per-team budgets, audit retention, PII redaction); coarse attribution (model/key/workspace); opaque routing (which provider served you is unclear); extra data hop (GDPR/HIPAA); single point of failure.
- **Complaints:** HN (2026-09-11): reasoning models "put everything in the reasoning field… you pay the whole cost and can't get anything out of it"; inconsistent strict-JSON forcing manual whitelists (http://news.ycombinator.com/item?id=49621546); **billing opacity incidents** (`openrouter/auto` hides which model was used and its cost; a 402 misclassified as "context overflow" triggered auto-compaction loops draining credits faster); non-refundable credits; unstable free-model availability.
- **Diagnosis gaps:** Shows *what* was spent, never *why* it changed or what to do; no anomaly alerting, no root-cause, no recommendations, no forecasting.
- **Differentiation:** **Structural conflict:** OpenRouter monetizes a 5.5% fee on your spend — it will never recommend spending less. A neutral tool ingests OpenRouter activity exports, diagnoses spikes (e.g., reasoning-token blowups its own UI surfaces poorly), recommends cheaper routes, and can quantify the 5.5% tax itself as a savings line item.

### 2.4 Newer gateways with cost positioning

- **Concentrate AI** — launched out of stealth June 2026, $5M+ from True Ventures/RRE; **free LLM gateway** with "spend controls built in by default." Launch quote: "Companies are no longer just asking how to use more AI. They are asking how to control it" (https://pr.mysugarlabel.example.net/article/Concentrate-AI-Launches-Free-LLM-Gateway-as-Companies-Race-to-Control-AI-Spend/6a296d8dd42e3400021c50c3). Early; depth **[unverified]**.
- **Provara** (syndicalt/provara, OSS) — ⚠️ **the closest thing to AI Cost Doctor inside a gateway**: "Spend Intelligence" dashboard with per-user/per-token attribution, MTD + run-rate forecasting, **7-vs-28-day spend anomaly detection**, quality-adjusted spend (judge scores next to cost), routing-weight drift correlation, **"quality-comparable savings recommendations,"** spend alerting with webhooks (https://github.com/syndicalt/provara). Most direct emerging competitor on the diagnosis axis — but requires adopting *its* gateway.
- **Alephant** — BYOK gateway; free tier (10k requests) with per-member cost attribution and "budget-safety guardrails" (https://blog.alephant.io/9-portkey-alternatives-for-byok-ai-gateways-in-2026/).
- **ScaleMind** (scalemind.ai) — AI gateway with automated cost optimization (smart cost routing, semantic caching, token rate limits, real-time cost tracking); blog is a cost-playbook ("How to Reduce LLM Costs by 40% in 24 Hours" — vendor claim). **Pricing could not be verified** (no pricing page found). Alive (blog actively maintained). Gateway, not diagnostician — savings are a side effect, not the product story.
- **TokenMix.ai** — OpenAI-compatible relay, 130+ models, intelligent routing, unified billing. **Pricing verified:** PAYG, top up from $1, ~5% markup on platform models, 0% BYOK; live 2026 pricing index content marketing (https://tokenmix.ai/pricing). Alive. No diagnosis layer.
- **Vercel AI Gateway** — $5/mo free credit per team, no-markup pass-through, Custom Reporting API (Pro/Enterprise) breaking spend by model/provider/user/feature.
- **Cloudflare AI Gateway** — free, basic cost/usage monitoring (100k logs free); observability-only, no budgets or diagnosis (https://tech-insider.org/cloudflare-ai-gateway-vs-portkey-vs-kong-2026/).

---

## 3. Cloud FinOps & Provider-Native Dashboards

### 3.1 CloudZero — "Financial control plane for AI spend"

- **AI cost analytics (2026):** All-in on AI: (1) **Real-time AI Spend** — agent/gateway connector capturing every AI API dollar at source in real time; (2) **AI Hub** — natural-language spend analysis (Claude-powered); rebuilt UI. Ingests spend **directly from OpenAI and Anthropic APIs** (claims first cloud-cost platform to do so), plus Bedrock/Azure OpenAI via cloud billing. Granularity: token-level (input/output/cached/reasoning as separate line items), per-model/feature/customer/team/SDLC-stage — **attribution without tags** via CostFormation. Model-level anomaly detection (reasoning-token spikes, prompt regressions, retry loops) → Slack; consumption-based forecasting. Cites Toyota, Duolingo, Coinbase, Shutterstock, Klaviyo, Upstart ($20M saved — vendor claim). Sources: https://www.cloudzero.com/blog/financial-control-plane-for-ai-spend/, https://www.cloudzero.com/blog/track-openai-spend/
- **Pricing:** **No public pricing** (Request Pricing only: https://www.cloudzero.com/pricing/). Third parties report **~$19 per $1,000 cloud spend/mo** (~1.9% of spend), custom above ~$50k spend **[third-party, unverified by vendor]**.
- **Target:** Mid-market to enterprise engineering/finance orgs.
- **Strengths:** Deepest AI attribution of any FinOps vendor; tag-free allocation; direct provider API integrations; real-time anomaly detection with owner routing; unit-economics heritage.
- **Weaknesses/complaints:** "Initial setup a bit complex… overwhelming for new users" (GetApp); dashboards require customer-success hand-holding, not full self-serve; "built-in optimization features are limited — users seeking automated savings may need extra tools"; exported data loses detail (SelectHub).
- **Diagnosis gaps:** Strong attribution and anomaly alerts, but cost-reduction guidance is generic playbook content, not dollar-quantified per-action recommendations; no self-serve tier a startup would buy.
- **Differentiation:** CloudZero's AI push is real but enterprise-priced and sales-led. A startup-native, self-serve, diagnosis-first tool undercuts on accessibility and price while matching the "what should I do" angle they only cover in marketing.

### 3.2 Vantage

- **AI cost analytics:** Native cost-ingestion connectors for Anthropic, OpenAI, Anyscale, Baseten, Cursor, ElevenLabs, Fireworks, Modal (https://www.vantage.sh/pricing). Dedicated feature: **LLM Token Allocation** (private preview, no extra cost) — joins per-request token observability (CloudWatch model-invocation logs for Bedrock, Datadog metrics, CSV upload) to billing rows **daily**, enriching cost with team/user/app metadata for Cost Reports, Virtual Tags, Segments, Alerts. **Private preview covers OpenAI + Bedrock only**; prompt content not collected (https://www.vantage.sh/blog/llm-token-allocation-preview).
- **Pricing (verified):** Starter **Free** (to $2,500/mo tracked spend, 3 users); Pro **$30/mo** (to $7,500, 5 users); Business **$200/mo** (to $20,000, 10 users); Enterprise custom. MCP server, cost recommendations, anomaly alerts included. Source: https://www.vantage.sh/pricing
- **Target:** Startups through mid-market; product-led, self-serve.
- **Strengths:** Cheap, transparent, self-serve — closest pricing fit to the AI Cost Doctor segment; Bedrock token enrichment via CloudWatch genuinely useful; the FinOps tool startups actually adopt early.
- **Weaknesses/complaints:** Allocation is preview/daily-batch/2 providers; **requires Bedrock model invocation logging enabled — off by default, per-account/per-region, no org-wide switch** (Vantage's own README acknowledges the friction); unmatched rows unenriched; recommendations generic infra, not AI-specific; tracked-spend caps mean the bill grows with your cloud bill.
- **Diagnosis gaps:** No "why did my bill change" root-cause; no per-action dollar-estimated savings; no unified cross-provider AI view.
- **Differentiation:** Vantage owns the *allocation* layer cheaply, not the *diagnosis* layer. An entrant leading with "why + what to do + how much it saves" across all providers in real time — without invocation-log plumbing — sits above it.

### 3.3 Datadog LLM Observability (rebranded "Agent Observability")

- **Cost features:** Observability, not FinOps: monitors latency, token usage, **estimated cost** across AI agents in real time; offline evaluators aligned to "quality, cost, latency KPIs." Third-party analysis claims per-request dollar estimates against published rates for 800+ models **[third-party claim, unverified on Datadog docs]**. Supports OpenAI, Anthropic, Gemini, Vertex, Bedrock, LangChain/CrewAI/LiteLLM, OTel. Billed per **LLM span**.
- **Pricing (verified):** Free $0/mo (40K spans/mo, 15-day retention); **Pro from $160/mo annual** (100K spans incl.; +$3.50/10K annual, $4.20 M2M, $5.00 on-demand); retention add-ons $1.50–$4.00/10K spans. Standalone (no other Datadog subscription required). Source: https://www.datadoghq.com/pricing/?product=llm-observability
- **Target:** Teams already on Datadog; AI-agent builders.
- **Strengths:** Best-in-class per-request tracing (great for *which prompt* is expensive); zero marginal setup if instrumented; per-request cost estimates in trace view.
- **Weaknesses/complaints:** **Span-based pricing punishes agentic apps** (one workflow = many spans); reports of **surprise auto-enablement billing** (~$120+/day when LLM spans detected); 15-day default retention criticized; general Datadog bill-shock lore ("Datadog cost more than our servers," https://medium.com/@devcommando/monitoring-everything-how-datadog-cost-more-than-our-servers-a8b81ecf36f3). No budgets, chargeback, or savings recommendations.
- **Diagnosis gaps:** "What did this trace cost," not "what should we do about the bill"; no cross-provider rollup; finance can't use it.
- **Differentiation:** Datadog's per-span cost anxiety is itself a wedge — position as the tool that keeps your *AI* spend sane, priced as a fraction of LLM spend with no per-span tax.

### 3.4 AWS Cost Explorer / Budgets (Bedrock)

- **Attribution (2026):** Baseline poor — **Cost Explorer shows Bedrock as a single line item; CUR gives usage-type dollars but no model/token dimensions** (https://medium.com/@arshikdhar2901/bedrock-emits-everything-you-need-to-track-costs-youre-just-not-querying-it-d8e4b913ddf6). 2026 primitives: **IAM Principal Attribution** (GA Apr 2026, per-identity billing in CUR 2.0); **Application Inference Profiles** (tagged profiles per app/feature, tags flow to Cost Explorer/CUR, survive cross-region routing); **Projects API** (Feb 2026, per-project tags, up to 1000/account — but **no per-request metadata tagging**, finest grain is per-usage-type/day). **Budgets alert on aggregates only — can't say which model is responsible.** The token data you want (InputTokenCount/OutputTokenCount by ModelId) sits **free in CloudWatch** but nobody queries it; model invocation logging is off by default per-account/per-region.
- **Pricing:** Free with AWS account.
- **Target:** AWS-native teams.
- **Complaints:** The canonical complaint: "can't attribute Bedrock costs to a specific app/user." Per-feature attribution still needs SDK/proxy wrapper; IAM principal too coarse (one service role hides many features); tag propagation lags 24–48h, not retroactive (https://github.com/optimnow/cloud-finops-skills/blob/HEAD/skills/cloud-finops/references/finops-bedrock.md).
- **Diagnosis gaps:** Everything — no AI anomaly detection, no recommendations, no per-prompt/per-tenant views without heavy DIY.
- **Differentiation:** AWS gives raw primitives requiring a platform team to assemble. A startup on Claude-on-Bedrock + OpenAI direct gets a unified, zero-plumbing view — the DIY tax is the wedge.

### 3.5 OpenAI usage/cost dashboard

- **Analytics:** Usage page: tokens and spend **per project, per model, per day** with graphs; org-level **Costs API**; billing history. **June 2026: Global Admin Console for ChatGPT Enterprise** — ChatGPT + Codex credit usage by user/product/model, per-workspace and per-team credit limits (https://www.thestreet.com/technology/openai-admits-enterprises-need-better-control-over-ai-costs) — an admission enterprises need cost control, but it serves ChatGPT Enterprise seats, not API-first startups.
- **Pricing:** Free with account.
- **Complaints:** "The usage dashboard is built for developers, not businesses… What you really need: cost per customer, per action, per outcome; real-time margin alerts; workflow-level profitability; which features are margin killers" (founder quote, https://paid.ai/blog/ai-monetization/you-need-ai-cost-tracking). "OpenAI: aggregated usage by day. No per-feature breakdown. No per-team allocation. No real-time alerts" (https://medium.com/@sin.nirbhaysingh/our-ai-bill-was-4-800-last-month-nobody-knew-why-so-i-built-an-open-source-llm-cost-tracker-018cdbdf9a6b). Multi-provider users reconcile separate dashboards.
- **Diagnosis gaps:** No root-cause, no recommendations, no per-customer/per-feature margin view, no anomaly alerts beyond spend caps.
- **Differentiation:** OpenAI will never show Anthropic/Bedrock spend side-by-side or tell you which feature is unprofitable. Cross-provider + per-customer margin is the gap.

### 3.6 Anthropic Console

- **Analytics:** Console usage page with token breakdowns; **workspaces** with spend limits and budget alerts (email/Slack); **Admin API** — Usage API (tokens in 1m/1h/1d buckets, groupable by API key/workspace/model/service tier/cache type) and Cost API (daily USD by workspace) — but requires a **separate admin API key + org account**, ~5 min lag; "an accounting feed, not a quota gauge." Claude Code `/cost` shows session cost. **Pro/Max subscription usage is console-only, no API.**
- **Pricing:** Free with account.
- **Complaints:** "Basic usage dashboard. No cost-per-request granularity. No budget enforcement"; individual accounts can't use Admin APIs; second privileged credential needed; Claude Code seat spend (huge for dev-tool startups) invisible to APIs.
- **Diagnosis gaps:** No anomaly detection, no recommendations, no cross-provider view, no per-feature/per-customer margin.
- **Differentiation:** Same as OpenAI — siloed, no diagnosis — plus the Claude Code seat-spend blind spot is a real startup pain point.

### 3.7 Azure OpenAI & Google Vertex AI billing (brief)

- **Azure OpenAI:** Standard Azure Cost Management — cost analysis by resource/subscription/**tags** (pass a `user` identifier per request; tag deployments by team for chargeback); billed per-token (Standard), hourly PTUs, 50%-off Batch. Microsoft **FinOps toolkit (Jan 2026)** added a FOCUS-aligned Azure OpenAI cost pattern (https://github.com/microsoft/finops-toolkit/blob/HEAD/announce/2026/2026-01_azure-openai-costs.md). Complaint: "Azure OpenAI bills by the token, but it does not tell you where the tokens went. The invoice is one number for the month" — no per-endpoint/per-feature view without DIY tagging.
- **Vertex AI / GCP:** Spend in the unified GCP bill. **April 2026: Google launched a FinOps AI Explainability Agent** — proactive cost-change analysis by model, modality, token consumption — plus Spend Caps on Cloud Budgets (private preview) and improved anomaly detection (FinOps Foundation Apr 2026 summit recap, https://www.youtube.com/watch?v=ZDWElwO0KSI). **Closest any hyperscaler has come to *diagnosis* — but GCP-only, new, unproven.**
- **Pricing:** Free with cloud account.
- **Diagnosis gaps:** Azure = raw allocation by tag, zero diagnosis. Google's agent is the one to watch; single-cloud and nascent.
- **Differentiation:** Multi-cloud reality: a startup on Azure OpenAI + Anthropic + Bedrock has no unified diagnosis anywhere.

### 3.8 Other FinOps entrants (2025–2026)

- **Finout** — MegaBill unified cost layer covering **OpenAI and Anthropic** alongside AWS/Azure/GCP/K8s/Snowflake/Databricks; **Finout Agents (June 2026)**: Detector/Investigator/Orchestrator agents that detect, root-cause, and remediate cost issues; **July 2026: native OpenAI Codex integration** converting credit billing to per-team dollars (https://www.businesswire.com/news/home/20260716517429/en/Finout-Becomes-the-First-FinOps-Platform-to-Turn-OpenAI-Codex-Spend-Into-a-Real-Dollar-Number-by-Team). **Pricing: G2 lists Business $1,000/month (provider-reported) [unverified by vendor]**; enterprise motion. Closest direct competitor on "AI cost intelligence" — but enterprise-priced.
- **Speridian "FinOps for AI" (June 2026)** — token budgeting/rate throttling, semantic cache routing (claims −40% tokens — vendor claim), multi-model routing, GPU analytics. Enterprise services firm, not a startup tool.
- **Ecosystem signal:** Linux Foundation announced a **Tokenomics Foundation** and **Tokenomicon** conference (June 2027) at FinOps X 2026; FinOps Foundation survey (Feb 2026): **98% of 1,192 practitioners now manage AI spend, up from 31% two years ago** (https://www.techtarget.com/searchcio/news/366644142/linux-foundation-announces-tokenomicon-at-finops-x). The category is real and accelerating.

---

## 4. Niche / Newer Cost-Focused Tools

### 4.1 Lytix (lytix.co) — 🟡 likely dormant, pivoted away from cost

- LLM observability + evals with cost/token dashboards; built `optimodel` (OSS) routing calls to the cheapest provider with fallbacks.
- **Pricing: could not verify** (no pricing page).
- Key finding: their blog post "Guaranteed Cheapest LLM Calls" carries an editor's note: *"we were originally excited about switching models based on cost. After some feedback from initial users, we learned that cost was not a primary issue, and would be even less of a concern as the LLMs get cheaper. We are now working on extending this model to help developers switch between models based on product and technical requirements."* (https://blog.lytix.co/posts/cheapest-llm-calls?ref=ai-recon.ghost.io)
- Status: blog footer "© 2024 lytix"; no 2025–2026 activity. **Lesson:** cost *tracking* alone wasn't compelling; they never tried prescriptive diagnosis — which is exactly the AI Cost Doctor wedge.

### 4.2 Murnitur (murnitur.ai) — 🔴 likely dead

- LLM observability ("DataDog for the AI world") with cost as a side feature; OTel-native; founded ~2023.
- **Pricing: could not verify.** Site unreachable as of Sep 2026; all coverage from 2024. Treat as abandoned.
- **Lesson:** generic LLM observability without a sharp wedge struggles to survive.

### 4.3 Unusd.ai — ❓ could not verify

- No public presence found under this name across multiple targeted searches. Either stealth/renamed/defunct or the name is off. **Do not treat as a confirmed competitor.**

### 4.4 TokenScope — ❓ no commercial B2B product found

- The name is shared by ≥5 unrelated OSS personal tools (macOS menu-bar Claude Code tracker, VS Code extension, Chrome extension with a Product Hunt listing, MCP server, AI proxy middleware) — all free/individual-developer tools, not B2B SaaS. If a commercial TokenScope exists, it has no discoverable website, pricing, or launch footprint. **Naming-collision risk** for anyone entering this space.

### 4.5 DoCoreAI — 🟢 alive, most genuinely cost-first

- Local-first, privacy-preserving **autonomous cost-control** sidecar (`pip install docoreai`): monkey-patches LLM SDK calls, tracks cost/tokens/latency per request *without capturing prompt content*, ML-predicts per-request token needs, replaces wasteful max-token ceilings, paces budgets across day/week, drift detection with auto-retrain, A/B-tests model changes. Claims 40–70% reduction across 20+ enterprise deployments (**vendor claim, undisclosed deployments**). Sources: https://pypi.org/project/docoreai/, https://medium.com/@docoreai/llm-cost-control-privacy-first-observability-docoreai-4fbf895fb1e7. Product Hunt launch Apr 2025; earlier OSS prompt-optimizer with 10k+ PyPI downloads in 40 days.
- **Pricing: partially verifiable** — free tier (10 prompts visualized, local collector); paid/enterprise pricing **could not verify** (no pricing page).
- **Target:** Enterprise AI teams; privacy-sensitive orgs.
- **Strengths:** Acts *before* overruns, not after; privacy-by-design (no prompt content leaves network) is a real enterprise differentiator; fails-open.
- **Weaknesses:** SDK monkey-patching is invasive and Python-only; enterprise sales motion, not self-serve; two product identities suggest pivoting.
- **Diagnosis gaps:** Autonomous control ≠ explainable diagnosis — it acts on your bill but doesn't obviously *show its work* ("here's what drove spend, what to change"). Enterprise-positioned, leaving seed–Series B self-serve open; no passive/gateway-agnostic mode.
- **Differentiation:** A passive, provider-agnostic diagnosis layer (read provider invoices/APIs — no proxy, no SDK surgery) for 5–100-dev startups is unserved.

### 4.6 LLM Observatory (OSS, davidaucancela/llm-observatory) — 🟢 alive

- Self-hosted MIT dashboard for Claude/OpenAI/Gemini: zero-overhead SDK wrapper, real-time WebSocket dashboard, cost & token tracking, budget alerts, Discord notifications, provider balance tracking, historical sync from provider APIs, **prompt cache hit tracking** (rare in free tools), CSV export. Updated 6 days ago (as of Sep 2026).
- **Pricing:** Free (self-hosted; no cloud offering).
- **Gaps:** Dashboard-only — tells you what you spent, not what to do. No recommendations, anomaly detection, or diagnosis. Anthropic/OpenAI/Gemini only. One-maintainer risk.
- **Lesson:** validates demand for cheap self-hosted cost visibility; the paid upgrade path is diagnosis, not more dashboards.

### 4.7 Adjacent launches (Product Hunt, 2026)

- **LangWatch "Claude Code usage tracking"** (Jul 30, 2026, 376 upvotes): per-session cost with cache read/write as separate token classes — incumbents moving into cost visibility.
- **agentfdr** (Jul 2026): local transcript reader with anomaly flags for token burns/loops — anomaly-detection UX exists but dev-only, not teams.
- **ClawCost** (Modology Studios): Claude API spend tracking, OSS + $19 Pro mentioned — pre/in-launch.
- **Claude Usage Tracker** (PH): free OSS macOS app — personal, not B2B.

---

## 5. Master Comparison Table

| Product | Cost angle: what it does | Pricing (verified unless noted) | Target customer | Strengths | Weaknesses / gaps | Notable user complaints |
|---|---|---|---|---|---|---|
| Langfuse | Per-generation cost tracking, dashboards by user/session/model | $0 → $29 → $199 → $2,499/mo; $8/100k units; self-host free | Eng teams wanting OSS observability | Best OSS feature set; 21k stars; prompt versioning; unlimited seats | No diagnosis/recommendations; unit billing balloons w/ agents; $300/mo SSO add-on | Unit-billing surprises; self-host ops burden |
| LangSmith | Token dashboards, cost-tracking doc, new Fleet cost alerting | Free → $39/seat/mo Plus → Enterprise custom (~$100k+/yr reported, unverified) | LangChain/LangGraph teams | Framework-native traces; agent views; compliance | Per-seat punishes growth; no OSS self-host; lock-in | Per-seat pricing grievances; broken multi-agent traces |
| Braintrust | Granular cost analytics per request/user/feature; gateway w/ caching+routing | Free → $249/mo Pro → Enterprise custom; $3/GB, $1.50/1k scores | Eval-driven teams, quality-critical agents | Best eval↔obs integration; IDE-native MCP; hybrid deploy | Highest entry price; GB+scores billing opaque; no full self-host | Pricing "justified only for large teams"; unintuitive metering |
| Helicone | Auto cost tracking 300+ models; cost-based rate limits; caching; threshold alerts | Free → $79/mo → $799/mo → Enterprise custom | Indie/small teams, drop-in logging | <5ms proxy; one-line integration; real cost optimization | **Maintenance mode since Mar 2026**; proxy-only visibility; $79→$799 jump | Existential: team joined Mintlify, no new features; "monitoring costs haven't followed API price drops" |
| Portkey | Per-request cost; 21+ metric analytics; ingress budget enforcement; semantic caching | Free → **$49/mo** → Enterprise custom; $9/100k req overage | AI startups; enterprise AI governance | 1,600+ models; metadata FinOps; OSS gateway (Mar 2026); great support | Log-metered pricing punishes history; unpriced models excluded from budgets; 30-day retention | Missing data export (G2); Bedrock cache-token cost bug; fallback config bugs |
| PromptLayer ⚠️ | **Runtime Intelligence: spend-change narratives, model-swap recs w/ $ savings + quality-risk replay** | Free → $49/mo (+$0.003/txn) → $500/mo → Enterprise custom | Prompt-ops teams, PMs | Only product w/ quantified savings recs; prompt versioning; A/B on live traffic | Scoped to own instrumentation; no cross-provider view; no tenant P&L; $0.003/txn at scale | Tight free tier; pricing unpredictability |
| LangWatch | Per-trace cost by user/feature/model; anomaly alerts; virtual-key budgets | Free → €29/seat/mo + usage → Enterprise custom | EU teams; OTel-native shops | OTel-native; per-agent cost; guardrails; audio pricing catalog | Small ecosystem; complex pricing; weak US/UK brand | None found (small footprint) |
| Arize/Phoenix | Per-span USD cost via OTel; no diagnosis layer | OSS free → AX Free → $50/mo Pro → Enterprise ~$50–100k/yr (unverified) | ML-native/enterprise w/ OTel | Best OTel traces; drift detection; framework breadth | Learning curve; Elastic license; **Dynatrace acquisition (Aug 2026)** uncertainty | Complexity; license gripes; pricing opacity |
| W&B Weave | Cost estimator; cost as eval dimension; manual-tag attribution | Free → ~$50/user/mo → Enterprise custom (unverified) | W&B-native ML teams | Experiment lineage; evals; Bedrock integration | Per-seat punishes segment; platform-coupled; CoreWeave roadmap risk | Per-seat #1 grievance; restrictive free tier |
| OpenLLMetry | Instrumentation only; cost DIY from token counts | OSS free; managed pricing unverified | OTel-instrumented teams | Zero lock-in; broadest coverage; 4 SDK languages | No UI/storage/cost logic at all | "You end up building it yourself" |
| LiteLLM | Per-request cost catalog; hard budget caps; cheapest/auto routing; caching | OSS free (~$200–500/mo infra, 3rd-party est.); Enterprise price unpublished (~$250/mo–$30k/yr unverified) | Enterprise platform teams; self-hosters | Widest provider breadth; best router; BYOK no markup | Self-host ops; **rough 2026 security record**; cost-accounting race conditions; streaming usage loss | Supply-chain compromise; exploited SQLi; privilege escalation; budget corruption race; latency overhead |
| OpenRouter | Unified bill, 0% markup, 5.5% credit fee; `:floor` cheapest routing; basic analytics | No subscription; prepaid credits + 5.5% fee; BYOK 5% above allowance | Indie hackers; experimenters; AI startups | Deepest catalog; transparent pricing; zero infra | Fee compounds; no RBAC/budgets; coarse attribution; opaque routing | Billing opacity incidents; reasoning-token blowups; non-refundable credits |
| Provara ⚠️ | **Spend Intelligence: anomaly detection (7v28d), run-rate forecast, quality-comparable savings recs** | OSS (self-host) | Gateway adopters | Most direct diagnosis overlap; per-user/per-token attribution | Requires adopting its gateway; early/OSS maturity | None found (too early) |
| CloudZero | Real-time AI spend; AI Hub NL analysis; tag-free attribution; anomaly → Slack | **No public pricing**; ~$19/$1k spend/mo (3rd-party, unverified) | Mid-market → enterprise | Deepest FinOps AI attribution; direct OpenAI+Anthropic APIs | Sales-led enterprise; complex setup; optimization features "limited" | Setup complexity; not self-serve; export data loss |
| Vantage | LLM Token Allocation (preview, daily, OpenAI+Bedrock); cheap allocation | **Free → $30 → $200/mo** → Enterprise custom | Startups → mid-market, self-serve | Cheapest credible FinOps; transparent; Bedrock token enrichment | Preview-only; daily batch; needs invocation logging enabled (off by default) | Preview friction; unmatched rows; generic recommendations |
| Datadog | Per-request est. cost in traces; quality/cost/latency KPIs | Free 40k spans → **from $160/mo** Pro | Datadog-native eng teams | Best trace debugging; zero setup if instrumented | **Per-span pricing punishes agents**; no finance workflow | Surprise auto-enablement billing; bill-shock lore |
| AWS Cost Explorer (Bedrock) | Service-level line item; 2026: IAM principal attribution, inference profiles, Projects API | Free | AWS-native teams | Native; free; new primitives | Attribution still DIY; budgets aggregate-only; logging off by default | "Can't attribute Bedrock costs to a specific app/user" |
| OpenAI dashboard | Per-project/model/day spend; Costs API; Enterprise admin console (Jun 2026) | Free | API users; ChatGPT Enterprise | Native; per-project breakdown | No per-customer/feature margin; no anomaly alerts; single-provider | "Built for developers, not businesses" |
| Anthropic Console | Per-workspace/model/key; Admin Usage+Cost APIs; workspace budgets | Free | API users | Workspaces; admin APIs | Separate admin key; no API for seat spend; siloed | "No cost-per-request granularity"; Claude Code spend invisible to APIs |
| Finout | MegaBill unified OpenAI+Anthropic+cloud; agentic Detector/Investigator (2026) | ~$1,000/mo Business (G2, unverified) | Enterprise | Closest "AI cost intelligence"; agentic root-cause | Enterprise-priced, enterprise motion | None found (enterprise, low public chatter) |
| DoCoreAI | Autonomous cost-control sidecar; predictive token ceilings; budget pacing | Free tier; paid pricing unverified | Enterprise AI teams; privacy-sensitive | Acts before overruns; privacy-by-design; fails-open | Python-only SDK patching; enterprise motion; acts opaquely | None found (early) |

---

## 6. Market Gaps — What Nobody Does Well

1. **Root-cause diagnosis of cost changes.** The single biggest gap. PromptLayer (scoped to its own instrumentation) and Provara (scoped to its gateway) are the only products that narrate *why* spend changed. Everyone else shows a chart and leaves the "why did my bill triple?" investigation — routinely 10+ engineering days — to the user.
2. **Dollar-quantified, quality-risk-aware savings recommendations.** Only PromptLayer ships these (model-swap recs with "$134/mo, low risk, 92% replay overlap"). Nobody quantifies caching ROI ("caching saved you $X this month"), routing ROI, or prompt-compression savings as a first-class analytics surface — despite every gateway *doing* caching/routing. Savings claims live in blog posts, not in product UX.
3. **Per-customer/tenant unit economics.** The emptiest cell and the most-quoted unmet need ("cost per customer, per action, per outcome… which features are margin killers" — paid.ai founder quote). Multi-tenant AI startups cannot answer "which customer is unprofitable." CloudZero approximates via allocation (enterprise only); nobody computes tenant P&L natively.
4. **Cross-provider unified diagnosis.** Only CloudZero (direct OpenAI+Anthropic APIs) and Finout (MegaBill) unify; Vantage covers 2 providers in preview; everything else is siloed. A startup on OpenAI + Claude + Bedrock has no single diagnostic pane.
5. **Anomaly detection with cost semantics.** LangWatch has generic anomaly alerts; Portkey's is enterprise-marketing; Provara's 7v28d is gateway-scoped. Nobody fires "spend on model X from feature Y is 3.8× baseline — here's the probable cause and the fix" to Slack for startups.
6. **Bill reconciliation / cost-data trust.** LiteLLM has documented budget race conditions and silently drops usage on aborted streams; Portkey had a Bedrock cache-token cost bug and excludes unpriced models from budgets. "Does my tracked spend match what providers actually billed?" is a real, unclaimed feature.
7. **Startup-accessible packaging.** The closest capabilities sit behind enterprise pricing and sales motions (CloudZero ~$19/$1k spend, Finout ~$1,000/mo, Speridian services). The self-serve $49–$399/mo slot with transparent pricing is open — most niche tools don't even publish pricing.
8. **Pricing-model alignment.** Observability tools tax the watching itself: per-seat (LangSmith $39, Weave $50, LangWatch €29), per-event/unit (Langfuse units, Braintrust GB+scores, Datadog spans), per-log (Portkey). A product priced as a small fraction of *LLM spend* — no seats, no per-event tax — is a pricing wedge all of them leave open.
9. **Zero-plumbing onboarding.** Vantage's Bedrock path requires enabling invocation logging (off by default, per-region, no org-wide switch); AWS attribution needs profiles/tags with 24–48h lag; gateways require traffic re-routing. "Connect provider keys → see diagnosis in 5 minutes" doesn't exist.

---

## 7. Wedge Options — Evidence For and Against

### Wedge A: Vendor-neutral cost-diagnosis layer ("the analytical brain, not the data pipe")

**What:** Ingest from anywhere — provider billing/cost APIs (OpenAI, Anthropic), CSV upload, proxy spend logs (LiteLLM, Portkey), OTel spans — with zero code changes and no gateway switch. Core loop: anomaly detection → "Investigate" root-cause narrative → dollar-quantified savings recommendations (model routing, caching, token hygiene) → Slack/email alerts. Priced as a fraction of LLM spend, no seats, no per-event tax.

**For:** The diagnosis gap is validated by the two closest competitors (PromptLayer proves willingness to pay for savings recs; Provara proves the anomaly+dollar-savings UX resonates) — and both are *scoped* (own instrumentation / own gateway), leaving the neutral position open. Every gateway and observability tool emits ingestible data (LiteLLM Postgres/spend logs, Portkey OTel+CSV, OpenRouter activity exports, Langfuse exports, OpenLLMetry spans) — distribution without re-instrumentation. Helicone's maintenance mode provides a ready migration audience already thinking in cost terms. Tiny-team shippable: deterministic cost math + statistical anomaly detection + LLM only for narratives (per the product brief's architecture). Aligns with the $49–$399/mo self-serve motion.

**Against:** PromptLayer could broaden beyond prompt-ops; Provara is OSS and could add provider-API ingest; CloudZero/Finout could eventually push downmarket. Defensibility rests on diagnosis quality and data breadth, not a moat — must win on velocity and focus. Requires building/maintaining a model-pricing catalog (mitigated: Portkey's is open-source).

### Wedge B: Per-customer/tenant cost attribution + margin analysis for B2B AI SaaS

**What:** "Which customer is unprofitable?" — per-tenant AI P&L: cost per customer, per feature, margin vs. plan price, margin-killer alerts. Sold to B2B AI startups whose unit economics depend on it (the highest willingness-to-pay sub-segment: it ties directly to their gross margin).

**For:** The emptiest cell in the market — literally nobody computes tenant P&L natively; the need is quoted verbatim by founders ("cost per customer, per action, per outcome; workflow-level profitability"). Highest willingness to pay (margin visibility justifies $149–$399/mo easily). Natural expansion into usage-based billing support.

**Against:** Requires customer/tenant metadata the buyer may not have plumbed — onboarding friction exactly where the product brief demands "under 5 minutes." Narrower initial TAM than Wedge A (only multi-tenant B2B SaaS, not all AI startups). Harder to demo without the buyer's own data. As a *standalone* wedge it's a feature in search of a product; it needs the diagnosis story around it to be purchasable.

**Verdict:** Powerful as the *killer feature and land motion within* Wedge A, weak as a standalone wedge.

### Wedge C: Bedrock-specific cost intelligence for AWS-native shops

**What:** Fix AWS's genuinely broken Bedrock attribution: unify Cost Explorer/CUR + CloudWatch token metrics + inference-profile tags into per-app/per-feature/per-model cost with anomaly detection — zero CloudWatch-query DIY.

**For:** The pain is acute and well-documented ("Bedrock shows as a single line item"; invocation logging off by default; tag lag 24–48h). Vantage only covers Bedrock in private preview, daily batch. AWS-native startups running Claude-on-Bedrock are a concentrated, reachable segment.

**Against:** Single-provider wedge leaves half the bill (OpenAI/Anthropic direct) unexplained — buyers will ask "what about the rest?" on day one. Requires wrestling AWS plumbing (the off-by-default logging problem applies to *us* too). Smaller TAM than the cross-provider play, and AWS could improve native tooling (Google already shipped an explainability agent — AWS may follow).

### Recommendation: **Wedge A, with Wedge B as the spearhead feature**

Ship the vendor-neutral diagnosis layer (Wedge A) as the product, and lead go-to-market with per-customer/tenant margin analysis (Wedge B) as the killer feature for B2B AI SaaS — the sub-segment with the clearest pain and highest willingness to pay. Rationale:

1. **It's the only gap validated by both competitor behavior and user complaints:** PromptLayer's Runtime Intelligence proves buyers want exactly this UX; its scoping (own instrumentation only) and Provara's (own gateway only) leave the neutral, ingest-anything position completely open.
2. **A tiny team can ship it:** deterministic cost math + statistical anomaly detection + LLM narratives is weeks of work, not months; no request-path infrastructure, no SDK, no proxy to operate (unlike every gateway competitor). Ingest via provider APIs + CSV on day one; proxy/OTel ingest in v1.1.
3. **It monetizes at the target price:** $49/mo Starter (1 project, anomaly alerts, savings recs) → $149/mo Growth (multi-project, tenant P&L, team access) → $399/mo Scale maps cleanly onto the $500–$50k/mo spend segment at ~1–10% of AI spend — in line with FinOps norms (CloudZero ~1.9% of spend) and far below the enterprise alternatives ($1k+/mo).
4. **Wedge B as spearhead solves the "why buy" for the best customers:** B2B AI SaaS founders feel margin pain personally; "we found your 3 unprofitable customers and $2,430/mo in savings" is a demo that sells itself, and it differentiates against PromptLayer (no tenant P&L) and every observability tool.
5. **Wedge C becomes an expansion play:** once the neutral layer exists, Bedrock deep-integration (CloudWatch token metrics, inference profiles) is a feature release, not a company bet.
6. **Timing is favorable:** 98% of FinOps practitioners now manage AI spend (FinOps Foundation, Feb 2026); Helicone's exit creates migratable demand; no credible startup-priced, self-serve, diagnosis-first player exists.

**What would invalidate this:** if PromptLayer ships cross-provider ingest + tenant P&L before we reach traction, or if OpenAI/Anthropic ship genuinely good native cost diagnosis (they have structural disincentives — OpenAI will never show Anthropic spend). Monitor both quarterly.

---

## 8. Market-Size Sanity Check (proxy signals — directional, not precise)

- **Category urgency:** FinOps Foundation survey (Feb 2026): **98% of 1,192 practitioners now manage AI spend, up from 31% two years ago** (https://www.techtarget.com/searchcio/news/366644142/linux-foundation-announces-tokenomicon-at-finops-x). The Linux Foundation is spinning up a Tokenomics Foundation with a Tokenomicon conference (June 2027) — institutional validation that AI cost management is a durable category.
- **Target segment spend:** The brief's segment (seed–Series B AI startups, $500–$50k/mo AI API spend) is the fastest-growing buyer cohort: YC alone funds hundreds of AI companies per batch; OpenRouter reports ~10M users (mid-2026, heavily indie/long-tail). If ~3,000–5,000 venture-funded AI startups/SaaS companies globally average ~$5k/mo in AI API spend, that's **$180M–$300M/yr in addressable AI API spend** — and FinOps tooling captures ~1–3% of managed spend (CloudZero ~1.9%), implying a **$2M–$9M/yr serviceable market at 1–3% capture for a startup-priced tool**, before expanding to mid-market. **[Rough proxy math — treat as directional, not a forecast.]**
- **Willingness to pay:** Established anchors: Portkey $49/mo, Helicone $79/mo, Datadog from $160/mo, Langfuse $29–199/mo, Finout ~$1,000/mo (enterprise). A $49–$399/mo ladder sits squarely in proven self-serve territory and represents ~1–10% of a $5k/mo AI bill — consistent with FinOps pricing norms.
- **Competitive mortality as signal:** Lytix pivoted away from cost ("cost was not a primary issue"); Murnitur appears dead; TokenScope/Unusd have no commercial footprint. Pure tracking doesn't sustain a business — but note the survivors monetize *adjacent* value (gateways take a cut of traffic; observability sells seats/events). A diagnosis product must prove ROI fast: quantified savings ≥10× the subscription is the bar for retention.
- **Headwind to watch:** Model prices fell ~80% since early 2025 (per Helicone-era commentary) — if inference keeps cheapening faster than usage grows, cost pain could soften at the low end. Counter: agentic workloads multiply token volumes (reasoning tokens, multi-step agents), and the FinOps survey trend says practitioner concern is *rising*, not falling.

---

## 9. Watchlist (revisit quarterly)

| Threat | Why | Trigger to worry |
|---|---|---|
| PromptLayer | Only shipper of quantified savings recs; could add cross-provider ingest + tenant P&L | Runtime Intelligence goes cross-provider |
| Provara (OSS) | Most direct feature overlap (anomaly + savings recs); OSS = fast iteration | Adds provider-API/CSV ingest (no gateway required) |
| CloudZero / Finout | Closest capabilities; could push downmarket | Launches sub-$200/mo self-serve tier |
| Google FinOps AI Explainability Agent | Only hyperscaler doing diagnosis; could set expectations | Expands beyond GCP or AWS copies it |
| Concentrate AI | $5M+ VC, free gateway with spend controls | Adds diagnosis UX on top of free gateway |
| OpenAI / Anthropic native dashboards | Structural disincentive to diagnose (they sell the tokens), but could improve reporting | Either ships anomaly alerts + recommendations |

---

## 10. Honesty Notes & Methodology Limits

- Pricing marked **[unverified]** or **[third-party]** was found only on aggregators, GitHub research docs, or vendor-adjacent blogs — not on the vendor's own pricing page. Verify live before citing externally.
- User complaints skew toward products with large public footprints (LiteLLM, Datadog, LangSmith). Early-stage tools (Provara, ScaleMind, TokenMix, DoCoreAI, Concentrate) have no meaningful public complaint record — absence of complaints ≠ satisfaction.
- Several 2026 events (acquisitions, launches, CVEs) were sourced from a mix of primary pages and third-party write-ups; where only one source type existed, it's noted.
- Unusd.ai and commercial TokenScope could not be verified to exist — the original brief's list should treat them as unconfirmed.
- This research reflects the public web as of 2026-09-21; LLM pricing and product packaging in this market move fast — re-verify pricing before fundraising or pricing decisions.
