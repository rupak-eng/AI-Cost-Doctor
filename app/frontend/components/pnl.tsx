/**
 * Shared Customer P&L view used by both the public demo (/demo) and the
 * authenticated app (/app/pnl). Pass `demo={true}` for the labeled synthetic
 * data view; `demo={false}` renders the neutral "Live data" caption instead of
 * the "Demo data" badge.
 */
import Link from "next/link";
import {
  ApiErrorNotice,
  DemoBadge,
  LiveDataCaption,
  SkeletonCard,
  StatusBadge,
} from "./ui";
import { formatUsd, PnlTenant } from "../lib/api";

function DataCaption({ demo }: { demo: boolean }) {
  return demo ? <DemoBadge /> : <LiveDataCaption />;
}

function TenantCard({
  tenant,
  demo,
  investigateHref,
}: {
  tenant: PnlTenant;
  demo: boolean;
  investigateHref: string;
}) {
  const marginPct =
    tenant.revenue_usd > 0 ? (tenant.margin_usd / tenant.revenue_usd) * 100 : null;
  const marginClass =
    tenant.status === "margin_killer"
      ? "text-red-700"
      : tenant.status === "at_risk"
        ? "text-amber-700"
        : tenant.status === "healthy"
          ? "text-emerald-700"
          : "text-slate-700";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">{tenant.name}</h3>
          <div className="mt-1">
            <DataCaption demo={demo} />
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
            {tenant.revenue_usd > 0 ? formatUsd(tenant.revenue_usd) : "—"}
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
            {tenant.revenue_usd > 0 ? formatUsd(tenant.margin_usd) : "—"}
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-slate-500">
        {marginPct != null
          ? `Margin is ${marginPct.toFixed(1)}% of revenue.`
          : "No revenue data for this customer yet — margin is unknown."}
      </p>
      <Link
        href={investigateHref}
        className="mt-5 inline-flex rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
      >
        Investigate
      </Link>
    </div>
  );
}

function MarginKillerSpotlight({
  tenant,
  investigateHref,
}: {
  tenant: PnlTenant;
  investigateHref: string;
}) {
  const loss = tenant.revenue_usd > 0 ? -tenant.margin_usd : tenant.ai_cost_usd;
  return (
    <div className="mb-8 rounded-xl border border-red-200 bg-red-50 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-red-700">
            Margin killer
          </p>
          <h2 className="mt-1 text-xl font-bold text-slate-900">
            {tenant.name} is costing you{" "}
            <span className="tabular-nums text-red-700">{formatUsd(loss)}</span>{" "}
            {tenant.revenue_usd > 0 ? "more than it pays you" : "with no revenue attached"}
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            AI cost {formatUsd(tenant.ai_cost_usd)}
            {tenant.revenue_usd > 0 && ` on ${formatUsd(tenant.revenue_usd)} revenue`}.
            Investigate the root cause and see what you can change.
          </p>
        </div>
        <Link
          href={investigateHref}
          className="inline-flex shrink-0 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800"
        >
          Investigate {tenant.name} →
        </Link>
      </div>
    </div>
  );
}

export interface PnlViewProps {
  /** true → "Demo data" badges + synthetic-data caption; false → "Live data" caption. */
  demo: boolean;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  tenants: PnlTenant[];
  /** Build the Investigate link for a tenant, e.g. (id) => `/demo/investigate?tenant=${id}`. */
  investigateHref: (tenantExternalId: string) => string;
  /** Rendered when loading is done and there are no tenants. */
  emptyState?: React.ReactNode;
}

export default function PnlView({
  demo,
  loading,
  error,
  onRetry,
  tenants,
  investigateHref,
  emptyState,
}: PnlViewProps) {
  const marginKiller = tenants
    .filter((t) => t.status === "margin_killer")
    .sort((a, b) => a.margin_usd - b.margin_usd)[0];
  return (
    <div>
      {marginKiller && !loading && !error && (
        <MarginKillerSpotlight
          tenant={marginKiller}
          investigateHref={investigateHref(marginKiller.tenant_external_id)}
        />
      )}
      <div className="max-w-3xl">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">
            Customer P&L
          </h1>
          <DataCaption demo={demo} />
        </div>
        <p className="mt-3 text-lg text-slate-600">
          Per-customer AI unit economics: revenue, AI cost, and gross AI margin for
          each customer.{" "}
          <span className="font-medium text-slate-800">Margin killers</span> —
          customers whose AI usage costs more than they pay you — are flagged for
          investigation.
        </p>
        {demo ? (
          <p className="mt-2 text-sm text-slate-500">
            This page uses labeled synthetic data computed by the same cost engine
            that powers real customer data. No figures are hardcoded.
          </p>
        ) : (
          <p className="mt-2 text-sm text-slate-500">
            Live customer data from your connected sources. All cost figures are
            computed by the AI Cost Doctor cost engine from usage events.
          </p>
        )}
      </div>

      <div className="mt-10">
        {loading && (
          <div className="grid gap-6 md:grid-cols-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}
        {error && <ApiErrorNotice error={error} onRetry={onRetry} />}
        {!loading && !error && tenants.length === 0 && emptyState}
        {!loading && !error && tenants.length > 0 && (
          <div className="grid gap-6 md:grid-cols-3">
            {tenants.map((t) => (
              <TenantCard
                key={t.tenant_id}
                tenant={t}
                demo={demo}
                investigateHref={investigateHref(t.tenant_external_id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
