/**
 * Shared Investigate view used by both the public demo (/demo/investigate) and
 * the authenticated app (/app/pnl/investigate). Pass `demo={true}` for the
 * labeled synthetic data view; `demo={false}` renders the neutral "Live data"
 * caption instead of the "Demo data" badge.
 *
 * The killer flow: "Why is this customer unprofitable?" -> driver breakdown
 * (model, application, volume-vs-tokens with dollar attribution, expensive
 * workflows) -> recommended actions with estimated monthly savings and
 * confidence -> "Estimates are not guarantees" disclaimer.
 */
import Link from "next/link";
import { ApiErrorNotice, CostBar, DemoBadge, LiveDataCaption } from "./ui";
import { formatUsd, InvestigateResponse, Recommendation } from "../lib/api";

function DataBadge({ demo }: { demo: boolean }) {
  return demo ? <DemoBadge /> : <LiveDataCaption />;
}

export interface InvestigateViewProps {
  /** true → "Demo data" badges; false → "Live data" captions. */
  demo: boolean;
  /** Selected tenant (external id). Null/empty → "no customer selected" notice. */
  tenantId: string;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  data: InvestigateResponse | null;
  backHref: string;
  backLabel: string;
}

function ConfidencePill({ confidence }: { confidence: string }) {
  const c = confidence.toLowerCase();
  const styles =
    c === "high"
      ? "bg-emerald-100 text-emerald-800 ring-emerald-200"
      : c === "medium"
        ? "bg-amber-100 text-amber-800 ring-amber-200"
        : "bg-slate-100 text-slate-700 ring-slate-200";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${styles}`}
    >
      {confidence} confidence
    </span>
  );
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  return (
    <div className="rounded-lg bg-white p-4 ring-1 ring-inset ring-slate-200">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">
          {rec.title || rec.action}
        </h3>
        <ConfidencePill confidence={rec.confidence} />
      </div>
      {rec.title && <p className="mt-1.5 text-sm text-slate-700">{rec.action}</p>}
      {rec.explanation && (
        <p className="mt-1.5 text-sm text-slate-600">{rec.explanation}</p>
      )}
      <dl className="mt-3 space-y-1.5">
        <div className="flex items-baseline justify-between">
          <dt className="text-xs text-slate-500">Estimated monthly savings</dt>
          <dd className="text-base font-bold tabular-nums text-emerald-700">
            {formatUsd(rec.est_savings_usd_mo)}
          </dd>
        </div>
        {rec.post_change_margin_usd != null && (
          <div className="flex items-baseline justify-between">
            <dt className="text-xs text-slate-500">Post-change margin</dt>
            <dd className="text-sm font-bold tabular-nums text-slate-900">
              {formatUsd(rec.post_change_margin_usd)}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function signedUsd(v: number): string {
  return `${v >= 0 ? "+" : "−"}${formatUsd(Math.abs(v))}`;
}

export default function InvestigateView({
  demo,
  tenantId,
  loading,
  error,
  onRetry,
  data,
  backHref,
  backLabel,
}: InvestigateViewProps) {
  const maxModel = data ? Math.max(0, ...data.drivers.by_model.map((m) => m.cost_usd)) : 0;
  const maxApp = data ? Math.max(0, ...data.drivers.by_app.map((a) => a.cost_usd)) : 0;
  const tenantName = data?.tenant_name || tenantId;
  // Prefer the full recommendations list; fall back to the legacy single rec.
  const recs: Recommendation[] =
    data?.recommendations && data.recommendations.length > 0
      ? data.recommendations
      : data?.recommendation
        ? [data.recommendation]
        : [];
  const disclaimer =
    data?.disclaimer || "Estimates are not guarantees.";
  const vvt = data?.volume_vs_tokens;
  const hasAttribution =
    vvt?.volume_effect_usd != null || vvt?.token_intensity_effect_usd != null;

  return (
    <div>
      <div className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">Investigate</h1>
            {tenantId && (
              <p className="mt-1 text-sm text-slate-600">
                Why is <span className="font-semibold text-slate-900">{tenantName}</span>{" "}
                {data?.margin_usd != null && data.margin_usd < 0 ? "unprofitable" : "spending this much"}
                {" "}on AI?
              </p>
            )}
          </div>
          <DataBadge demo={demo} />
        </div>
        <Link href={backHref} className="text-sm font-semibold text-indigo-600 hover:text-indigo-800">
          ← {backLabel}
        </Link>
      </div>

      {!tenantId && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-800">
          No customer selected.{" "}
          <Link href={backHref} className="font-semibold underline">
            Go back to the Customer P&L
          </Link>{" "}
          and pick one to investigate.
        </div>
      )}

      {tenantId && loading && (
        <div className="space-y-4">
          <div className="h-6 w-1/2 animate-pulse rounded bg-slate-200" />
          <div className="h-32 animate-pulse rounded-xl bg-slate-200" />
          <div className="h-48 animate-pulse rounded-xl bg-slate-200" />
        </div>
      )}

      {tenantId && error && <ApiErrorNotice error={error} onRetry={onRetry} />}

      {tenantId && !loading && !error && data && (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            {/* Summary */}
            <section className="rounded-xl border border-slate-200 bg-white p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-900">Cost diagnosis</h2>
                <DataBadge demo={demo} />
              </div>
              <p className="mt-3 text-slate-700">{data.summary}</p>
            </section>

            {/* Cost by model */}
            <section className="rounded-xl border border-slate-200 bg-white p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-900">Cost by model</h2>
                <DataBadge demo={demo} />
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
                <DataBadge demo={demo} />
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
                <DataBadge demo={demo} />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-4">
                <div className="rounded-lg bg-slate-50 p-4 text-center">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Request volume</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">
                    {data.volume_vs_tokens.volume_change_pct != null
                      ? `${data.volume_vs_tokens.volume_change_pct >= 0 ? "+" : ""}${data.volume_vs_tokens.volume_change_pct.toFixed(1)}%`
                      : "—"}
                  </p>
                  {vvt?.volume_effect_usd != null && (
                    <p className="mt-1 text-sm font-semibold tabular-nums text-slate-600">
                      {signedUsd(vvt.volume_effect_usd)}
                    </p>
                  )}
                </div>
                <div className="rounded-lg bg-slate-50 p-4 text-center">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Tokens per request</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">
                    {data.volume_vs_tokens.tokens_change_pct != null
                      ? `${data.volume_vs_tokens.tokens_change_pct >= 0 ? "+" : ""}${data.volume_vs_tokens.tokens_change_pct.toFixed(1)}%`
                      : "—"}
                  </p>
                  {vvt?.token_intensity_effect_usd != null && (
                    <p className="mt-1 text-sm font-semibold tabular-nums text-slate-600">
                      {signedUsd(vvt.token_intensity_effect_usd)}
                    </p>
                  )}
                </div>
              </div>
              {hasAttribution && (
                <p className="mt-3 text-sm text-slate-600">
                  Dollar attribution of the cost change:{" "}
                  <span className="font-semibold tabular-nums">
                    {signedUsd(vvt?.volume_effect_usd ?? 0)}
                  </span>{" "}
                  from request volume,{" "}
                  <span className="font-semibold tabular-nums">
                    {signedUsd(vvt?.token_intensity_effect_usd ?? 0)}
                  </span>{" "}
                  from tokens per request
                  {vvt?.mix_effect_usd != null && (
                    <>
                      ,{" "}
                      <span className="font-semibold tabular-nums">
                        {signedUsd(vvt.mix_effect_usd)}
                      </span>{" "}
                      from model/price mix
                    </>
                  )}
                  .
                </p>
              )}
              {data.volume_vs_tokens.note && (
                <p className="mt-2 text-sm text-slate-500">{data.volume_vs_tokens.note}</p>
              )}
            </section>

            {/* Expensive workflows */}
            <section className="rounded-xl border border-slate-200 bg-white p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-900">Expensive workflows</h2>
                <DataBadge demo={demo} />
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

          {/* Recommended actions */}
          <div className="lg:col-span-1">
            <section className="sticky top-6 rounded-xl border border-indigo-200 bg-indigo-50/60 p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-900">Recommended actions</h2>
                <DataBadge demo={demo} />
              </div>
              {recs.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {recs.map((rec, i) => (
                    <RecommendationCard key={`${rec.type}-${i}`} rec={rec} />
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-slate-600">
                  No savings opportunity above the cost threshold was found for this customer.
                </p>
              )}
              <p className="mt-5 rounded-lg bg-white p-3 text-xs text-slate-500 ring-1 ring-inset ring-slate-200">
                {disclaimer} Savings are estimates computed from this
                customer&apos;s usage data and labeled with a confidence level.
              </p>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
