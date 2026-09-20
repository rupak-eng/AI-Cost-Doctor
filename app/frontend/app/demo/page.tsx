"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiErrorNotice,
  DemoBadge,
  SkeletonCard,
  StatusBadge,
} from "../../components/ui";
import { DemoPnlResponse, fetchDemoPnl, formatUsd } from "../../lib/api";

function TenantCard({ tenant }: { tenant: DemoPnlResponse["tenants"][number] }) {
  const marginPct =
    tenant.revenue_usd > 0 ? (tenant.margin_usd / tenant.revenue_usd) * 100 : 0;
  const marginClass =
    tenant.status === "margin_killer"
      ? "text-red-700"
      : tenant.status === "at_risk"
        ? "text-amber-700"
        : "text-emerald-700";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">{tenant.name}</h3>
          <div className="mt-1">
            <DemoBadge />
          </div>
        </div>
        <StatusBadge status={tenant.status} />
      </div>
      <dl className="mt-5 grid grid-cols-3 gap-4">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Monthly revenue
          </dt>
          <dd className="mt-1 text-lg font-bold tabular-nums text-slate-900">
            {formatUsd(tenant.revenue_usd)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
            AI cost
          </dt>
          <dd className="mt-1 text-lg font-bold tabular-nums text-slate-900">
            {formatUsd(tenant.ai_cost_usd)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Gross AI margin
          </dt>
          <dd className={`mt-1 text-lg font-bold tabular-nums ${marginClass}`}>
            {formatUsd(tenant.margin_usd)}
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-slate-500">
        Margin is {marginPct.toFixed(1)}% of revenue.
      </p>
      <Link
        href={`/demo/investigate?tenant=${encodeURIComponent(tenant.tenant_external_id)}`}
        className="mt-5 inline-flex rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
      >
        Investigate
      </Link>
    </div>
  );
}

export default function DemoPage() {
  const [data, setData] = useState<DemoPnlResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchDemoPnl()
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">$</span>
            <span className="text-lg font-semibold tracking-tight text-slate-900">AI Cost Doctor</span>
          </Link>
          <div className="flex items-center gap-3">
            <DemoBadge />
            <Link href="/signup" className="text-sm font-semibold text-indigo-600 hover:text-indigo-800">
              Sign up →
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-12">
        <div className="max-w-3xl">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">
              Customer P&L
            </h1>
            <DemoBadge />
          </div>
          <p className="mt-3 text-lg text-slate-600">
            Per-customer AI unit economics: revenue, AI cost, and gross AI margin for
            each customer. <span className="font-medium text-slate-800">Margin killers</span> —
            customers whose AI usage costs more than they pay you — are flagged for
            investigation.
          </p>
          <p className="mt-2 text-sm text-slate-500">
            This page uses labeled synthetic data computed by the same cost engine that
            powers real customer data. No figures are hardcoded.
          </p>
        </div>

        <div className="mt-10">
          {loading && (
            <div className="grid gap-6 md:grid-cols-3">
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </div>
          )}
          {error && <ApiErrorNotice error={error} onRetry={load} />}
          {!loading && !error && data && (
            <div className="grid gap-6 md:grid-cols-3">
              {data.tenants.map((t) => (
                <TenantCard key={t.tenant_id} tenant={t} />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
