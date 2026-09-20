import { cn } from "./cn";

const STATUS_STYLES: Record<string, string> = {
  margin_killer: "bg-red-50 text-red-700 ring-red-600/20",
  at_risk: "bg-amber-50 text-amber-700 ring-amber-600/25",
  healthy: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
};

const STATUS_LABELS: Record<string, string> = {
  margin_killer: "Margin Killer",
  at_risk: "At Risk",
  healthy: "Healthy",
};

/** Required on every demo view and demo data card. */
export function DemoBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-800 ring-1 ring-inset ring-indigo-600/20",
        className
      )}
      title="This view uses labeled synthetic data computed by the same cost engine as real data."
    >
      Demo data
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700 ring-slate-600/20";
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset", style)}>
      {label}
    </span>
  );
}

/** Friendly inline error used when the API cannot be reached. */
export function ApiErrorNotice({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-800" role="alert">
      <p className="font-semibold">Couldn&apos;t load this data</p>
      <p className="mt-1">{error.message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-md bg-red-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-800"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-slate-200 bg-white p-5">
      <div className="h-4 w-1/3 rounded bg-slate-200" />
      <div className="mt-4 h-8 w-2/3 rounded bg-slate-200" />
      <div className="mt-3 h-4 w-1/2 rounded bg-slate-200" />
    </div>
  );
}

/** Simple horizontal bar row for cost breakdowns. */
export function CostBar({
  label,
  sub,
  cost,
  max,
}: {
  label: string;
  sub?: string;
  cost: number;
  max: number;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (cost / max) * 100)) : 0;
  return (
    <div className="py-2">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-800">{label}</p>
          {sub && <p className="truncate text-xs text-slate-500">{sub}</p>}
        </div>
        <p className="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
          ${cost.toLocaleString("en-US", { maximumFractionDigits: 2 })}
        </p>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-indigo-600" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
