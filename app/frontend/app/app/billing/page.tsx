"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiErrorNotice, SkeletonCard } from "../../../components/ui";
import {
  BillingStatus,
  PLAN_CATALOG,
  PlanName,
  createCheckoutSession,
  createPortalSession,
  fetchBillingStatus,
} from "../../../lib/api";
import { cn } from "../../../components/cn";

function PlanCard({
  plan,
  current,
  effectivePlan,
  onChoose,
  busy,
  checkoutDisabled,
}: {
  plan: Exclude<PlanName, "free">;
  current: PlanName;
  effectivePlan: PlanName;
  onChoose: (plan: Exclude<PlanName, "free">) => void;
  busy: string | null;
  checkoutDisabled: boolean;
}) {
  const info = PLAN_CATALOG[plan];
  const isCurrent = effectivePlan === plan;
  return (
    <div
      className={cn(
        "flex flex-col rounded-xl border bg-white p-6",
        isCurrent ? "border-indigo-500 ring-2 ring-indigo-100" : "border-slate-200"
      )}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900">{info.name}</h3>
        {isCurrent && (
          <span className="rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-semibold text-indigo-700">
            Current plan
          </span>
        )}
      </div>
      <p className="mt-1 text-3xl font-bold text-slate-900">{info.price}</p>
      <p className="mt-2 text-sm text-slate-600">{info.blurb}</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm text-slate-700">
        {info.features.map((f) => (
          <li key={f} className="flex items-start gap-2">
            <span className="mt-0.5 text-indigo-600">✓</span>
            <span>{f}</span>
          </li>
        ))}
      </ul>
      <button
        onClick={() => onChoose(plan)}
        disabled={isCurrent || busy !== null || checkoutDisabled}
        title={checkoutDisabled ? "Online checkout is not configured on this deployment" : undefined}
        className={cn(
          "mt-6 rounded-lg px-4 py-2 text-sm font-semibold",
          isCurrent || checkoutDisabled
            ? "cursor-default bg-slate-100 text-slate-400"
            : "bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
        )}
      >
        {isCurrent ? "Active" : busy === plan ? "Redirecting…" : `Choose ${info.name}`}
      </button>
      {current === "free" && !isCurrent && (
        <p className="mt-2 text-xs text-slate-500">14-day free trial, no card required.</p>
      )}
    </div>
  );
}

export default function BillingPage() {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchBillingStatus().then(setStatus).catch((e) => setError(e as Error));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // After Stripe redirects back, refresh state and show a notice.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const flag = params.get("checkout");
    if (flag === "cancelled") {
      setNotice("Checkout was cancelled — no charge was made. Your trial is unchanged.");
      load();
      window.history.replaceState({}, "", "/app/billing");
    } else if (flag === "success") {
      setNotice(
        "Payment confirmed — your plan is activating. If it doesn't update within a minute, refresh this page."
      );
      load();
      window.history.replaceState({}, "", "/app/billing");
    }
  }, [load]);

  const choose = async (plan: Exclude<PlanName, "free">) => {
    setBusy(plan);
    setNotice(null);
    try {
      const session = await createCheckoutSession(plan);
      window.location.href = session.url; // Stripe-hosted checkout
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Could not start checkout.");
      setBusy(null);
    }
  };

  const openPortal = async () => {
    setBusy("portal");
    try {
      const session = await createPortalSession();
      window.location.href = session.url; // Stripe customer portal
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Could not open the billing portal.");
      setBusy(null);
    }
  };

  if (error) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Billing</h1>
        <div className="mt-4">
          <ApiErrorNotice error={error} onRetry={load} />
        </div>
      </div>
    );
  }
  if (!status) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Billing</h1>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  const trialBanner = status.trial_active && status.trial_days_left !== null && (
    <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-900">
      <span className="font-semibold">Free trial:</span> {status.trial_days_left}{" "}
      {status.trial_days_left === 1 ? "day" : "days"} left with full access — no card
      required. Pick a plan below to keep provider sync and anomaly alerts running.
    </div>
  );

  const pastDue = status.subscription_status === "past_due" && (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <span className="font-semibold">Payment failed.</span> Your subscription is past
      due — update your payment method in the billing portal to avoid interruption.
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-900">Billing</h1>
        {status.stripe_customer_id && (
          <button
            onClick={openPortal}
            disabled={busy !== null}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {busy === "portal" ? "Opening…" : "Manage subscription"}
          </button>
        )}
      </div>

      {trialBanner}
      {pastDue}
      {!status.stripe_configured && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          Online checkout isn&rsquo;t configured on this deployment yet — your trial
          gives you full access in the meantime.
        </div>
      )}
      {notice && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          {notice}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <PlanCard
          plan="starter"
          current={status.plan}
          effectivePlan={status.effective_plan}
          onChoose={choose}
          busy={busy}
          checkoutDisabled={!status.stripe_configured}
        />
        <PlanCard
          plan="growth"
          current={status.plan}
          effectivePlan={status.effective_plan}
          onChoose={choose}
          busy={busy}
          checkoutDisabled={!status.stripe_configured}
        />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Current usage
        </h2>
        <dl className="mt-3 grid gap-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-slate-500">Events this month</dt>
            <dd className="mt-1 text-lg font-semibold text-slate-900">
              {status.events_this_month.toLocaleString()}
              <span className="ml-1 text-sm font-normal text-slate-500">
                / {status.limits.events_per_month.toLocaleString()}
              </span>
            </dd>
            {status.events_over_limit && (
              <dd className="mt-1 text-xs text-amber-700">
                Over your plan&rsquo;s soft event limit — ingestion keeps working, but
                consider upgrading.
              </dd>
            )}
          </div>
          <div>
            <dt className="text-slate-500">Projects</dt>
            <dd className="mt-1 text-lg font-semibold text-slate-900">
              {status.projects_count}{" "}
              <span className="text-sm font-normal text-slate-500">
                / {status.limits.max_projects}
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Data retention</dt>
            <dd className="mt-1 text-lg font-semibold text-slate-900">
              {status.limits.retention_days} days
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-slate-500">
          Billing is handled securely by Stripe. AI Cost Doctor never sees or stores your
          card details.
        </p>
      </div>

      <p className="text-sm text-slate-500">
        <Link href="/app" className="text-indigo-600 hover:underline">
          ← Back to overview
        </Link>
      </p>
    </div>
  );
}
