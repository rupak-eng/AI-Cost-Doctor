"use client";

import Link from "next/link";

/** Shown on the Overview dashboard when the selected project has no usage data yet. */
export default function OverviewEmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-100 text-xl font-bold text-indigo-700">
        $
      </div>
      <h2 className="mt-4 text-xl font-bold text-slate-900">Connect your AI stack to see your customer P&L</h2>
      <p className="mx-auto mt-2 max-w-xl text-slate-600">
        Once usage data is flowing, this view shows per-customer AI unit economics:
        revenue, AI cost, and gross AI margin per customer — with margin killers
        flagged for investigation.
      </p>
      <div className="mx-auto mt-8 grid max-w-2xl gap-4 text-left md:grid-cols-3">
        {[
          {
            title: "OpenAI + Anthropic",
            body: "Connect provider usage APIs with an Admin API key. Keys are encrypted and validated before anything is stored.",
            tag: "Available now",
            href: "/app/connect",
          },
          {
            title: "CSV upload",
            body: "Drop in a billing export with guided column mapping and a dry-run preview.",
            tag: "Available now",
            href: "/app/connect",
          },
          {
            title: "Event API",
            body: "POST usage events with a per-project API key.",
            tag: "Available now",
            href: "/app/connect",
          },
        ].map((c) => (
          <div key={c.title} className="rounded-lg border border-slate-200 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{c.tag}</p>
            <h3 className="mt-1 font-semibold text-slate-900">{c.title}</h3>
            <p className="mt-1 text-sm text-slate-600">{c.body}</p>
            {c.href && (
              <Link href={c.href} className="mt-2 inline-block text-sm font-semibold text-indigo-600 hover:text-indigo-800">
                Go to Connect →
              </Link>
            )}
          </div>
        ))}
      </div>
      <p className="mt-8 text-sm text-slate-500">
        Want to see what it looks like?{" "}
        <Link href="/demo" className="font-semibold text-indigo-600 hover:text-indigo-800">
          Explore the interactive demo
        </Link>{" "}
        — labeled synthetic data, no signup needed.
      </p>
    </div>
  );
}
