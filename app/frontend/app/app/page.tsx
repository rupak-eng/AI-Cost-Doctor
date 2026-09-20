"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import OverviewEmptyState from "../../components/overview-empty-state";
import ProjectSelector from "../../components/project-selector";
import AnomaliesFeed from "../../components/anomalies-feed";
import { ApiErrorNotice, CostBar, LiveDataCaption, SkeletonCard } from "../../components/ui";
import {
  AnomaliesResponse,
  BillingStatus,
  DashboardDays,
  DashboardResponse,
  PnlResponse,
  fetchBillingStatus,
  fetchProjectAnomalies,
  fetchProjectDashboard,
  fetchProjectPnl,
  formatUsd,
} from "../../lib/api";
import { useProjects } from "../../lib/project";
import { cn } from "../../components/cn";

const PERIODS: { label: string; days: DashboardDays }[] = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

function TrendChart({ points }: { points: { date: string; cost_usd: number }[] }) {
  const max = Math.max(...points.map((p) => p.cost_usd), 0);
  const width = 640;
  const height = 160;
  const barW = width / points.length;
  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label="Daily AI spend trend"
      >
        {points.map((p, i) => {
          const h = max > 0 ? Math.max(2, (p.cost_usd / max) * (height - 24)) : 0;
          return (
            <g key={p.date}>
              <title>{`${p.date}: $${p.cost_usd.toFixed(2)}`}</title>
              <rect
                x={i * barW + barW * 0.2}
                y={height - h}
                width={Math.max(1, barW * 0.6)}
                height={h}
                rx={2}
                className="fill-indigo-500"
              />
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between text-xs text-slate-400">
        <span>{points[0]?.date}</span>
        <span>{points[points.length - 1]?.date}</span>
      </div>
    </div>
  );
}

function MarginKillerBanner({ pnl }: { pnl: PnlResponse }) {
  const killer = pnl.tenants
    .filter((t) => t.status === "margin_killer")
    .sort((a, b) => a.margin_usd - b.margin_usd)[0];
  if (!killer) return null;
  const loss = killer.revenue_usd > 0 ? -killer.margin_usd : killer.ai_cost_usd;
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-800">
          <span className="font-semibold uppercase tracking-wide text-red-700 text-xs">
            Margin killer&nbsp;·&nbsp;
          </span>
          <span className="font-semibold text-slate-900">{killer.name}</span> is
          costing you{" "}
          <span className="font-bold tabular-nums text-red-700">{formatUsd(loss)}</span>{" "}
          {killer.revenue_usd > 0 ? "more than it pays you" : "with no revenue attached"}.
        </p>
        <Link
          href={`/app/pnl/investigate?tenant=${encodeURIComponent(killer.tenant_external_id)}`}
          className="inline-flex shrink-0 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800"
        >
          Investigate →
        </Link>
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const projects = useProjects();
  const projectId = projects.selected?.id ?? null;
  const [days, setDays] = useState<DashboardDays>(30);
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [pnl, setPnl] = useState<PnlResponse | null>(null);
  const [anomalies, setAnomalies] = useState<AnomaliesResponse | null>(null);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!projectId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([
      fetchProjectDashboard(projectId, days),
      fetchProjectPnl(projectId),
      fetchProjectAnomalies(projectId, days),
    ])
      .then(([d, p, a]) => {
        setData(d);
        setPnl(p);
        setAnomalies(a);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e : new Error("Couldn't load the dashboard.")))
      .finally(() => setLoading(false));
  }, [projectId, days]);

  useEffect(() => {
    if (!projects.loading) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.loading, projectId, days]);

  useEffect(() => {
    if (!projects.loading) {
      fetchBillingStatus().then(setBilling).catch(() => setBilling(null));
    }
  }, [projects.loading]);

  const busy = projects.loading || loading;
  const empty = !busy && !error && data && data.total_requests === 0;

  const handleAcknowledged = useCallback((id: string) => {
    setAnomalies((prev) => {
      if (!prev) return prev;
      const anomalies = prev.anomalies.map((a) =>
        a.id === id ? { ...a, status: "acknowledged" as const } : a
      );
      return {
        ...prev,
        anomalies,
        unread_count: anomalies.filter((a) => a.status === "open").length,
      };
    });
  }, []);

  const showTrialBanner =
    billing !== null &&
    billing.trial_active &&
    billing.trial_days_left !== null &&
    billing.trial_days_left <= 7;

  return (
    <div>
      {showTrialBanner && (
        <div className="mb-6 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-900">
          <span className="font-semibold">Free trial ending soon:</span>{" "}
          {billing!.trial_days_left} {billing!.trial_days_left === 1 ? "day" : "days"}{" "}
          left with full access.{" "}
          <Link href="/app/billing" className="font-semibold underline hover:no-underline">
            Choose a plan
          </Link>{" "}
          to keep provider sync and anomaly alerts running.
        </div>
      )}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Overview</h1>
            <LiveDataCaption />
          </div>
          <p className="mt-1 text-sm text-slate-600">
            AI spend for{" "}
            <span className="font-semibold text-slate-900">
              {projects.selected?.name ?? "your project"}
            </span>
            . Every figure is computed by the cost engine from usage events.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1" role="group" aria-label="Period">
            {PERIODS.map((p) => (
              <button
                key={p.days}
                onClick={() => setDays(p.days)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium",
                  days === p.days
                    ? "bg-indigo-600 text-white"
                    : "text-slate-600 hover:text-slate-900"
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <ProjectSelector state={projects} />
        </div>
      </div>

      {projects.error && <ApiErrorNotice error={projects.error} onRetry={projects.reload} />}
      {error && <ApiErrorNotice error={error} onRetry={load} />}

      {busy && (
        <div className="grid gap-6 md:grid-cols-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      )}

      {!busy && !error && empty && <OverviewEmptyState />}

      {!busy && !error && !empty && data && (
        <div className="space-y-6">
          {pnl && <MarginKillerBanner pnl={pnl} />}

          {projectId && anomalies && (
            <AnomaliesFeed
              projectId={projectId}
              anomalies={anomalies.anomalies}
              unreadCount={anomalies.unread_count}
              days={anomalies.days}
              onAcknowledged={handleAcknowledged}
            />
          )}

          <div className="grid gap-6 md:grid-cols-4">
            {[
              { label: "Total AI spend", value: formatUsd(data.total_cost_usd), sub: `last ${data.days} days` },
              { label: "Requests", value: data.total_requests.toLocaleString("en-US"), sub: `last ${data.days} days` },
              {
                label: "Avg cost / 1k requests",
                value: data.total_requests > 0 ? formatUsd((data.total_cost_usd / data.total_requests) * 1000) : "—",
                sub: "unit cost of serving",
              },
              {
                label: "Unpriced events",
                value: data.unpriced_events.toLocaleString("en-US"),
                sub: "no catalog price — cost unknown",
              },
            ].map((k) => (
              <div key={k.label} className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{k.label}</p>
                <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">{k.value}</p>
                <p className="mt-1 text-xs text-slate-500">{k.sub}</p>
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h2 className="text-sm font-semibold text-slate-900">Spend trend</h2>
            <p className="mt-0.5 text-xs text-slate-500">Daily AI cost (calculated) over the selected period.</p>
            <div className="mt-4">
              <TrendChart points={data.trend} />
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-white p-6">
              <h2 className="text-sm font-semibold text-slate-900">Spend by model</h2>
              <p className="mt-0.5 text-xs text-slate-500">Which models drive your cost.</p>
              <div className="mt-2 divide-y divide-slate-100">
                {data.by_model.slice(0, 8).map((r) => (
                  <CostBar
                    key={`${r.provider}/${r.model}`}
                    label={r.model}
                    sub={`${r.provider} · ${r.requests.toLocaleString("en-US")} requests · ${r.share_pct}%`}
                    cost={r.cost_usd}
                    max={data.by_model[0]?.cost_usd ?? 0}
                  />
                ))}
                {data.by_model.length === 0 && (
                  <p className="py-4 text-sm text-slate-500">No model data in this period.</p>
                )}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-6">
              <h2 className="text-sm font-semibold text-slate-900">Spend by application</h2>
              <p className="mt-0.5 text-xs text-slate-500">Which features drive your cost.</p>
              <div className="mt-2 divide-y divide-slate-100">
                {data.by_application.slice(0, 8).map((r) => (
                  <CostBar
                    key={r.application}
                    label={r.application}
                    sub={`${r.requests.toLocaleString("en-US")} requests · ${r.share_pct}%`}
                    cost={r.cost_usd}
                    max={data.by_application[0]?.cost_usd ?? 0}
                  />
                ))}
                {data.by_application.length === 0 && (
                  <p className="py-4 text-sm text-slate-500">No application data in this period.</p>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Top cost-driving customers</h2>
                <p className="mt-0.5 text-xs text-slate-500">Customers ranked by AI cost in the selected period.</p>
              </div>
              <Link href="/app/pnl" className="text-sm font-semibold text-indigo-600 hover:text-indigo-800">
                Full customer P&L →
              </Link>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                    <th className="pb-2 pr-4 font-medium">Customer</th>
                    <th className="pb-2 pr-4 font-medium text-right">AI cost</th>
                    <th className="pb-2 font-medium text-right">Requests</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.top_tenants.slice(0, 10).map((t) => (
                    <tr key={t.tenant_external_id ?? "unattributed"}>
                      <td className="py-2.5 pr-4 font-medium text-slate-900">
                        {t.tenant_name ?? t.tenant_external_id ?? "Unattributed"}
                      </td>
                      <td className="py-2.5 pr-4 text-right tabular-nums text-slate-900">
                        {formatUsd(t.cost_usd)}
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-slate-600">
                        {t.requests.toLocaleString("en-US")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.top_tenants.length === 0 && (
                <p className="py-4 text-sm text-slate-500">No tenant data in this period.</p>
              )}
            </div>
          </div>

          <p className="text-xs text-slate-500">
            Cost basis: calculated — deterministic pricing from the AI Cost Doctor
            catalog. Provider-reported totals are kept separate and never mixed
            into these figures.
          </p>
        </div>
      )}
    </div>
  );
}
