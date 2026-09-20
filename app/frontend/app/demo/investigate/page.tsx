"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { DemoBadge } from "../../../components/ui";
import InvestigateView from "../../../components/investigate-view";
import {
  InvestigateResponse,
  fetchDemoInvestigate,
} from "../../../lib/api";

function InvestigateContent() {
  const params = useSearchParams();
  const tenantId = params.get("tenant") ?? "";
  const [data, setData] = useState<InvestigateResponse | null>(null);
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
        <InvestigateView
          demo
          tenantId={tenantId}
          loading={loading}
          error={error}
          onRetry={load}
          data={data}
          backHref="/demo"
          backLabel="Back to Customer P&L"
        />
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
