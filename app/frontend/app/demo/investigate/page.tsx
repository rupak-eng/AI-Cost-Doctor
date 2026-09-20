"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  ApiErrorNotice,
  CostBar,
  DemoBadge,
} from "../../../components/ui";
import {
  DemoInvestigateResponse,
  fetchDemoInvestigate,
  formatUsd,
} from "../../../lib/api";

function InvestigateContent() {
  const params = useSearchParams();
  const tenantId = params.get("tenant") ?? "";
  const [data, setData] = useState<DemoInvestigateResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetchDemoInvestigate(tenantId)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  const maxModel = data ? Math.max(0, ...data.drivers.by_model.map((m) => m.cost_usd)) : 0;
  const maxApp = data ? Math.max(0, ...data.drivers.by_app.map((a) => a.cost_usd)) : 0;
  const rec = data?.recommendation;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">$</span>
            <span className="text-lg font-semibold tracking-tight text-slate-900">AI Cost Doctor</span>
          </Link>
          <DemoBadge />
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-12">
        <div className="mb-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">Investigate</h1>
            <DemoBadge />
          </div>
          <Link href="/demo" className="text-sm font-semibold text-indigo-600 hover:text-indigo-800">
            ← Back to Customer P&L
          </Link>
        </div>

        {!tenantId && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-800">
            No customer selected. <Link href="/demo" className="font-semibold underline">Go back to the Customer P&L</Link> and pick one to investigate.
          </div>
        )}

        {tenantId && loading && (
          <div className="space-y-4">
            <div className="h-6 w-1/2 animate-pulse rounded bg-slate-200" />
            <div className="h-32 animate-pulse rounded-xl bg-slate-200" />
            <div className="h-48 animate-pulse rounded-xl bg-slate-200" />
          </div>
        )}

        {tenantId && error && <ApiErrorNotice error={error} onRetry={load} />}

        {tenantId && !loading && !error && data && (
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-2">
              {/* Summary */}
              <section className="rounded-xl border border-slate-200 bg-white p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-slate-900">Cost diagnosis</h2>
                  <DemoBadge />
                </div>
                <p className="mt-3 text-slate-700">{data.summary}</p>
              </section>

              {/* Cost by model */}
              <section className="rounded-xl border border-slate-200 bg-white p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-slate-900">Cost by model</h2>
                  <DemoBadge />
                </div>
                <div className="mt-2 divide-y divide-slate-100">
                  {data.drivers.by_model.map((m) => (
                    <CostBar key={m.key} label={m.label} sub={m.share_pct != null ? `${m.share_pct.toFixed(1)}% of cost` : undefined} cost={m.cost_usd} max={maxModel} />
                  ))}
                  {data.drivers.by_model.length === 0 && <p className="py-4 text-sm text-slate-500">No model breakdown available.</p>}
                </div>
              </section>

              {/* Cost by application */}
              <section className="rounded-xl border border-slate-200 bg-white p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-slate-900">Cost by application</h2>
                  <DemoBadge />
                </div>
                <div className="mt-2 divide-y divide-slate-100">
                  {data.drivers.by_app.map((a) => (
                    <CostBar key={a.key} label={a.label} sub={a.share_pct != null ? `${a.share_pct.toFixed(1)}% of cost` : undefined} cost={a.cost_usd} max={maxApp} />
                  ))}
                  {data.drivers.by_app.length === 0 && <p className="py-4 text-sm text-slate-500">No application breakdown available.</p>}
                </div>
              </section>

              {/* Volume vs tokens */}
              <section className="rounded-xl border border-slate-200 bg-white p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-slate-900">Volume vs. token change</h2>
                  <DemoBadge />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-4">
                  <div className="rounded-lg bg-slate-50 p-4 text-center">
                    <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Request volume</p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">
                      {data.volume_vs_tokens.volume_change_pct != null
                        ? `${data.volume_vs_tokens.volume_change_pct >= 0 ? "+" : ""}${data.volume_vs_tokens.volume_change_pct.toFixed(1)}%`
                        : "—"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-slate-50 p-4 text-center">
                    <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Tokens per request</p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">
                      {data.volume_vs_tokens.tokens_change_pct != null
                        ? `${data.volume_vs_tokens.tokens_change_pct >= 0 ? "+" : ""}${data.volume_vs_tokens.tokens_change_pct.toFixed(1)}%`
                        : "—"}
                    </p>
                  </div>
                </div>
                {data.volume_vs_tokens.note && (
                  <p className="mt-3 text-sm text-slate-600">{data.volume_vs_tokens.note}</p>
                )}
              </section>

              {/* Expensive workflows */}
              <section className="rounded-xl border border-slate-200 bg-white p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-slate-900">Expensive workflows</h2>
                  <DemoBadge />
                </div>
                {data.expensive_workflows.length > 0 ? (
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead>
                        <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                          <th className="py-2 pr-4 font-medium">Workflow</th>
                          <th className="py-2 pr-4 font-medium">Model</th>
                          <th className="py-2 pr-4 font-medium">Requests</th>
                          <th className="py-2 font-medium">Cost</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {data.expensive_workflows.map((w, i) => (
                          <tr key={i}>
                            <td className="py-2.5 pr-4 font-medium text-slate-900">{w.workflow ?? w.name ?? "—"}</td>
                            <td className="py-2.5 pr-4 text-slate-600">{w.model ?? "—"}</td>
                            <td className="py-2.5 pr-4 tabular-nums text-slate-600">{w.requests?.toLocaleString("en-US") ?? "—"}</td>
                            <td className="py-2.5 tabular-nums font-semibold text-slate-900">
                              {w.cost_usd != null ? formatUsd(w.cost_usd) : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="py-4 text-sm text-slate-500">No expensive workflows identified.</p>
                )}
              </section>
            </div>

            {/* Recommendation */}
            <div className="lg:col-span-1">
              {rec && (
                <section className="sticky top-6 rounded-xl border border-indigo-200 bg-indigo-50/60 p-6">
                  <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-slate-900">Recommendation</h2>
                    <DemoBadge />
                  </div>
                  <p className="mt-3 text-slate-700">{rec.action}</p>
                  <dl className="mt-5 space-y-3">
                    <div className="flex items-baseline justify-between">
                      <dt className="text-sm text-slate-600">Estimated monthly savings</dt>
                      <dd className="text-lg font-bold tabular-nums text-emerald-700">
                        {formatUsd(rec.est_savings_usd_mo)}
                      </dd>
                    </div>
                    <div className="flex items-baseline justify-between">
                      <dt className="text-sm text-slate-600">Confidence</dt>
                      <dd className="text-sm font-semibold text-slate-900">{rec.confidence}</dd>
                    </div>
                    <div className="flex items-baseline justify-between">
                      <dt className="text-sm text-slate-600">Post-change margin</dt>
                      <dd className="text-sm font-bold tabular-nums text-slate-900">
                        {formatUsd(rec.post_change_margin_usd)}
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-5 rounded-lg bg-white p-3 text-xs text-slate-500 ring-1 ring-inset ring-slate-200">
                    Estimates are not guaranteed. Savings are estimates computed from this
                    customer&apos;s usage data and labeled with a confidence level.
                  </p>
                </section>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default function DemoInvestigatePage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50 p-12 text-slate-500">Loading…</div>}>
      <InvestigateContent />
    </Suspense>
  );
}
