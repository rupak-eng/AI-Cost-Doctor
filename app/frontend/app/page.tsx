import Link from "next/link";

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
            $
          </span>
          <span className="text-lg font-semibold tracking-tight text-slate-900">AI Cost Doctor</span>
        </Link>
        <nav className="hidden items-center gap-8 text-sm font-medium text-slate-600 md:flex">
          <a href="#problem" className="hover:text-slate-900">Problem</a>
          <a href="#how" className="hover:text-slate-900">How it works</a>
          <a href="#diagnosis" className="hover:text-slate-900">Diagnosis</a>
          <a href="#pricing" className="hover:text-slate-900">Pricing</a>
          <a href="#faq" className="hover:text-slate-900">FAQ</a>
        </nav>
        <div className="flex items-center gap-3">
          <Link href="/login" className="text-sm font-medium text-slate-600 hover:text-slate-900">
            Sign in
          </Link>
          <Link
            href="/signup"
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            Analyze My AI Spend
          </Link>
        </div>
      </div>
    </header>
  );
}

function SectionHeading({ kicker, title, lede }: { kicker: string; title: string; lede?: string }) {
  return (
    <div className="mx-auto max-w-3xl text-center">
      <p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">{kicker}</p>
      <h2 className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{title}</h2>
      {lede && <p className="mt-4 text-lg text-slate-600">{lede}</p>}
    </div>
  );
}

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      <Nav />

      {/* Hero */}
      <section className="border-b border-slate-200 bg-slate-50">
        <div className="mx-auto max-w-7xl px-6 py-24 sm:py-32">
          <div className="mx-auto max-w-3xl text-center">
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-6xl">
              Find where your AI budget is leaking.
            </h1>
            <p className="mt-6 text-xl text-slate-600">
              Per-customer AI unit economics for B2B AI products: which customers are
              unprofitable, why, and what to change to fix it. Cost diagnosis that ends
              in dollar-quantified potential savings — not another cost chart.
            </p>
            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Link
                href="/signup"
                className="w-full rounded-lg bg-indigo-600 px-8 py-3.5 text-base font-semibold text-white hover:bg-indigo-700 sm:w-auto"
              >
                Analyze My AI Spend
              </Link>
              <Link
                href="/demo"
                className="w-full rounded-lg border border-slate-300 bg-white px-8 py-3.5 text-base font-semibold text-slate-900 hover:border-slate-400 sm:w-auto"
              >
                See How It Works
              </Link>
            </div>
            <p className="mt-4 text-sm text-slate-500">
              No credit card. Interactive demo runs on labeled synthetic data — no signup, no API key.
            </p>
          </div>
        </div>
      </section>

      {/* Problem */}
      <section id="problem" className="py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading
            kicker="The problem"
            title="Your biggest AI customers may be your most unprofitable"
            lede="Usage-based revenue with flat pricing means a handful of power users can quietly erase the margin of your entire plan. Provider billing tells you the total — not which customer caused it."
          />
          <div className="mt-16 grid gap-6 md:grid-cols-3">
            {[
              {
                title: "Invisible margin killers",
                body: "One customer running heavy support-agent workflows on a flagship model can cost more in tokens than they pay you per month. You only notice when the quarter's numbers land.",
              },
              {
                title: "Cost without attribution",
                body: "OpenAI shows your spend, Anthropic shows theirs — neither shows which application, workflow, or customer is driving it, and neither will ever show the other's bill.",
              },
              {
                title: "Investigation eats the savings",
                body: "Every cost spike turns into an afternoon of spreadsheet forensics across providers, models, and tenants. By the time you find the cause, another month has leaked.",
              },
            ].map((c) => (
              <div key={c.title} className="rounded-xl border border-slate-200 bg-white p-8">
                <h3 className="text-lg font-semibold text-slate-900">{c.title}</h3>
                <p className="mt-3 text-slate-600">{c.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="border-y border-slate-200 bg-slate-50 py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading
            kicker="How it works"
            title="From raw usage to customer profitability in four steps"
          />
          <div className="mt-16 grid gap-6 md:grid-cols-4">
            {[
              { n: "1", title: "Connect", body: "Bring your usage data: OpenAI and Anthropic usage APIs, a CSV export, or our event API. No gateway, no code changes." },
              { n: "2", title: "See per-customer P&L", body: "Every customer's AI cost is computed from a versioned pricing catalog and matched against their revenue. Margin killers surface automatically." },
              { n: "3", title: "Investigate", body: "One click opens the cost diagnosis: which model, which application, volume vs. token changes, and the expensive workflows behind the spike." },
              { n: "4", title: "Save", body: "Get recommended actions — model routing, prompt caching, token hygiene — each with estimated monthly savings and a confidence level." },
            ].map((s) => (
              <div key={s.n} className="rounded-xl border border-slate-200 bg-white p-6">
                <p className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-600 text-sm font-bold text-white">{s.n}</p>
                <h3 className="mt-4 text-lg font-semibold text-slate-900">{s.title}</h3>
                <p className="mt-2 text-sm text-slate-600">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Sample diagnosis */}
      <section id="diagnosis" className="py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading
            kicker="Cost diagnosis"
            title="An example of what the diagnosis finds"
            lede="Excerpt from the interactive demo (clearly labeled synthetic data):"
          />
          <div className="mx-auto mt-12 max-w-3xl rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-slate-900">Customer A — Investigate</h3>
              <span className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-700 ring-1 ring-inset ring-red-600/20">
                Margin Killer
              </span>
            </div>
            <dl className="mt-6 grid grid-cols-3 gap-4 text-center">
              <div className="rounded-lg bg-slate-50 p-4">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Monthly revenue</dt>
                <dd className="mt-1 text-xl font-bold text-slate-900">$499</dd>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">AI cost</dt>
                <dd className="mt-1 text-xl font-bold text-slate-900">$681</dd>
              </div>
              <div className="rounded-lg bg-red-50 p-4">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Gross AI margin</dt>
                <dd className="mt-1 text-xl font-bold text-red-700">−$182</dd>
              </div>
            </dl>
            <p className="mt-6 text-slate-700">
              <span className="font-semibold text-slate-900">Root cause:</span> 73% of cost comes
              from the Support Agent; 81% of that is GPT-4.1 running a classification workflow.
              Routing that workflow to a cheaper model saves an estimated <span className="font-semibold">$140/mo</span>,
              improving the customer margin from −$182 to about −$42 (confidence: Medium).
            </p>
            <Link href="/demo/investigate?tenant=customer-a" className="mt-4 inline-block text-sm font-semibold text-indigo-600 hover:text-indigo-800">
              Try this diagnosis in the interactive demo →
            </Link>
          </div>
        </div>
      </section>

      {/* Savings */}
      <section className="border-y border-slate-200 bg-slate-900 py-24">
        <div className="mx-auto max-w-7xl px-6">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-xs font-semibold uppercase tracking-widest text-indigo-300">Savings</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Savings tied to your spend, not our seat count
            </h2>
            <p className="mt-4 text-lg text-slate-300">
              Every recommendation shows its current cost, estimated monthly savings, and a
              confidence level. We price the product as a small fraction of AI spend — so it
              only makes sense if the savings clearly exceed the subscription.
            </p>
          </div>
          <div className="mx-auto mt-12 grid max-w-4xl gap-6 md:grid-cols-3">
            {[
              { title: "Model routing", body: "Move classification and extraction workloads to cheaper models where quality holds." },
              { title: "Prompt caching", body: "Cache repeated system prompts and context instead of re-sending them on every request." },
              { title: "Token hygiene", body: "Trim verbose prompts, cap runaway max-tokens, and deduplicate repeated calls." },
            ].map((c) => (
              <div key={c.title} className="rounded-xl border border-slate-700 bg-slate-800 p-6">
                <h3 className="font-semibold text-white">{c.title}</h3>
                <p className="mt-2 text-sm text-slate-300">{c.body}</p>
              </div>
            ))}
          </div>
          <p className="mx-auto mt-8 max-w-3xl text-center text-sm text-slate-400">
            Savings figures are estimates based on your actual usage data — presented as estimates, never guaranteed.
          </p>
        </div>
      </section>

      {/* Data sources */}
      <section className="py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading
            kicker="Data sources"
            title="Bring your usage data, however you have it"
          />
          <div className="mx-auto mt-12 grid max-w-4xl gap-6 md:grid-cols-2">
            {[
              { title: "OpenAI", body: "Connect OpenAI cost and usage APIs to pull usage directly. Where the provider API can't supply a field, we tell you — CSV or the event API is the honest fallback." },
              { title: "Anthropic", body: "Connect the Admin Usage and Cost APIs. Dual-key onboarding keeps credentials scoped to what billing ingest needs." },
              { title: "CSV upload", body: "Drop in a billing export with guided column mapping. A dry-run preview shows parsed rows and computed cost before anything is committed." },
              { title: "Event API", body: "POST usage events with a per-project API key — eight fields: timestamp, provider, model, application, tenant, input/output tokens, and cost." },
            ].map((c) => (
              <div key={c.title} className="rounded-xl border border-slate-200 bg-white p-6">
                <h3 className="font-semibold text-slate-900">{c.title}</h3>
                <p className="mt-2 text-sm text-slate-600">{c.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Security */}
      <section className="border-y border-slate-200 bg-slate-50 py-24">
        <div className="mx-auto max-w-4xl px-6">
          <SectionHeading kicker="Security" title="Your billing data stays yours" />
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {[
              { title: "Encryption", body: "Credentials are stored with envelope encryption — never in plaintext. Traffic is encrypted in transit." },
              { title: "Tenant isolation", body: "Multi-tenant from day one: every query is scoped to your org. Customer A can never see Customer B's costs." },
              { title: "Least privilege", body: "Provider keys are scoped to billing read access only. Event-ingest API keys are hashed at rest and shown once at creation." },
            ].map((c) => (
              <div key={c.title} className="rounded-xl border border-slate-200 bg-white p-6">
                <h3 className="font-semibold text-slate-900">{c.title}</h3>
                <p className="mt-2 text-sm text-slate-600">{c.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading
            kicker="Pricing"
            title="A fraction of your AI spend"
            lede="No per-seat tax, no per-event tax. Priced against the savings we find."
          />
          <div className="mx-auto mt-12 grid max-w-5xl gap-6 md:grid-cols-4">
            {[
              { name: "Free", price: "$0", features: ["1 project", "Basic cost analytics", "CSV upload"] },
              { name: "Starter", price: "$49/mo", features: ["1 project", "Anomaly detection", "Savings recommendations"], highlight: true },
              { name: "Growth", price: "$149/mo", features: ["Multi-project", "Tenant P&L", "Team access", "Cost history"] },
              { name: "Scale", price: "$399/mo", features: ["Multi-team", "Advanced integrations", "Extended retention", "Priority support"] },
            ].map((t) => (
              <div
                key={t.name}
                className={`rounded-xl border p-6 ${t.highlight ? "border-indigo-600 bg-indigo-50/50 ring-1 ring-indigo-600" : "border-slate-200 bg-white"}`}
              >
                <h3 className="font-semibold text-slate-900">{t.name}</h3>
                <p className="mt-2 text-2xl font-bold text-slate-900">{t.price}</p>
                <ul className="mt-4 space-y-2 text-sm text-slate-600">
                  {t.features.map((f) => (
                    <li key={f}>• {f}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="mt-8 text-center text-sm text-slate-500">
            Billing is coming soon — plans shown above are the target pricing.
          </p>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="border-t border-slate-200 bg-slate-50 py-24">
        <div className="mx-auto max-w-3xl px-6">
          <SectionHeading kicker="FAQ" title="Frequently asked questions" />
          <div className="mt-12 space-y-4">
            {[
              {
                q: "Is this another LLM observability tool?",
                a: "No. Observability shows you requests and traces; we answer a finance question: which customers are profitable given their AI usage, why, and what to change. Cost charts are supporting detail — the diagnosis is the product.",
              },
              {
                q: "Do I need to change my code or adopt a gateway?",
                a: "No. We ingest from provider billing APIs, CSV exports, or a lightweight event API. There's no proxy to adopt and no code changes required.",
              },
              {
                q: "How do you compute cost?",
                a: "Every usage event is priced deterministically from a versioned pricing catalog with effective dates. The UI distinguishes reported cost (what the provider billed) from calculated cost (what our engine computed) and estimated savings.",
              },
              {
                q: "Are the savings recommendations guaranteed?",
                a: "No. Estimated savings are computed from your actual usage data and labeled with a confidence level. They are estimates, never guaranteed.",
              },
              {
                q: "What data do you need about my customers?",
                a: "Just a customer identifier and their monthly revenue — enough to compute per-customer AI unit economics. We never need their content or end-user data.",
              },
              {
                q: "Is my data isolated from other customers?",
                a: "Yes. The system is multi-tenant from day one with per-org isolation; every query is scoped to your organization.",
              },
            ].map((f) => (
              <details key={f.q} className="rounded-xl border border-slate-200 bg-white p-6">
                <summary className="cursor-pointer font-semibold text-slate-900">{f.q}</summary>
                <p className="mt-3 text-slate-600">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA + footer */}
      <section className="py-24">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900">Find where your AI budget is leaking.</h2>
          <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link href="/signup" className="w-full rounded-lg bg-indigo-600 px-8 py-3.5 text-base font-semibold text-white hover:bg-indigo-700 sm:w-auto">
              Analyze My AI Spend
            </Link>
            <Link href="/demo" className="w-full rounded-lg border border-slate-300 bg-white px-8 py-3.5 text-base font-semibold text-slate-900 hover:border-slate-400 sm:w-auto">
              See How It Works
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white py-12">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-6 px-6 md:flex-row">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-xs font-bold text-white">$</span>
            <span className="font-semibold text-slate-900">AI Cost Doctor</span>
          </div>
          <nav className="flex gap-6 text-sm text-slate-500">
            <Link href="/demo" className="hover:text-slate-900">Demo</Link>
            <Link href="/signup" className="hover:text-slate-900">Sign up</Link>
            <Link href="/login" className="hover:text-slate-900">Sign in</Link>
          </nav>
          <p className="text-sm text-slate-400">© 2026 AI Cost Doctor. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
