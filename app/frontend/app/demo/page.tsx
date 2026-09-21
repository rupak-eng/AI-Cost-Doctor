"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DemoBadge } from "../../components/ui";
import PnlView from "../../components/pnl";
import { PnlResponse, fetchDemoPnl } from "../../lib/api";

export default function DemoPage() {
  const [data, setData] = useState<PnlResponse | null>(null);
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
        <p className="mb-8 max-w-3xl text-sm text-slate-500">
          You&apos;re exploring a sample AI company on labeled synthetic data.
          Find the margin killer below, then click{" "}
          <span className="font-medium text-slate-700">Investigate</span> to see
          the root-cause diagnosis and what you could change.
        </p>
        <PnlView
          demo
          loading={loading}
          error={error}
          onRetry={load}
          tenants={data?.tenants ?? []}
          investigateHref={(tenantExternalId) =>
            `/demo/investigate?tenant=${encodeURIComponent(tenantExternalId)}`
          }
        />
      </main>
    </div>
  );
}
