"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "../../lib/auth";
import { cn } from "../../components/cn";

const NAV = [
  { label: "Overview", href: "/app", section: "overview" },
  { label: "Customer P&L", href: "/app/pnl", section: "pnl" },
  { label: "Investigate", href: "/app/investigate", section: "investigate" },
  { label: "Savings", href: "/app/savings", section: "savings" },
  { label: "Settings", href: "/app/settings", section: "settings" },
];

function Placeholder({ title, section }: { title: string; section: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
        This section is coming in a later phase. Connect your AI stack first — then
        your {section} will show up here.
      </p>
    </div>
  );
}

function OverviewEmptyState() {
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
            body: "Connect provider usage APIs directly. Coming in Phase 4.",
            tag: "Coming soon",
          },
          {
            title: "CSV upload",
            body: "Drop in a billing export with guided column mapping and a dry-run preview. Coming in Phase 3.",
            tag: "Coming soon",
          },
          {
            title: "Event API",
            body: "POST usage events with a per-project API key. Coming in Phase 3.",
            tag: "Coming soon",
          },
        ].map((c) => (
          <div key={c.title} className="rounded-lg border border-slate-200 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{c.tag}</p>
            <h3 className="mt-1 font-semibold text-slate-900">{c.title}</h3>
            <p className="mt-1 text-sm text-slate-600">{c.body}</p>
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

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading, logout, user } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      setRedirecting(true);
      router.replace("/login");
    }
  }, [loading, isAuthenticated, router]);

  if (loading || redirecting || !isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex h-16 items-center border-b border-slate-200 px-5">
          <Link href="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">$</span>
            <span className="font-semibold tracking-tight text-slate-900">AI Cost Doctor</span>
          </Link>
        </div>
        <nav className="flex-1 space-y-1 p-4">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "block rounded-lg px-3 py-2 text-sm font-medium",
                  active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-slate-200 p-4">
          <p className="truncate text-xs text-slate-500">
            {typeof user?.email === "string" ? user.email : "Signed in"}
          </p>
          <button onClick={logout} className="mt-2 text-sm font-medium text-slate-600 hover:text-slate-900">
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-6 md:hidden">
          <span className="font-semibold text-slate-900">AI Cost Doctor</span>
          <Link href="/demo" className="text-sm font-medium text-indigo-600">Demo</Link>
        </header>
        <main className="flex-1 p-6 md:p-10">
          {pathname === "/app" ? (
            <>
              <h1 className="text-2xl font-bold tracking-tight text-slate-900">Overview</h1>
              <p className="mt-1 text-sm text-slate-600">Your customer P&L at a glance.</p>
              <div className="mt-6">
                <OverviewEmptyState />
              </div>
            </>
          ) : pathname === "/app/pnl" ? (
            <Placeholder title="Customer P&L" section="per-customer P&L" />
          ) : pathname === "/app/investigate" ? (
            <Placeholder title="Investigate" section="cost diagnosis" />
          ) : pathname === "/app/savings" ? (
            <Placeholder title="Savings" section="savings recommendations" />
          ) : pathname === "/app/settings" ? (
            <Placeholder title="Settings" section="settings" />
          ) : (
            children
          )}
        </main>
      </div>
    </div>
  );
}
