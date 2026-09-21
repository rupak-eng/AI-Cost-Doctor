"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "../../lib/auth";
import { cn } from "../../components/cn";

const NAV = [
  { label: "Overview", href: "/app" },
  { label: "Customer P&L", href: "/app/pnl" },
  { label: "Connect", href: "/app/connect" },
  { label: "Billing", href: "/app/billing" },
  { label: "Investigate", comingSoon: true },
  { label: "Savings", comingSoon: true },
  { label: "Settings", comingSoon: true },
];

const PLACEHOLDERS: Record<string, { title: string; section: string }> = {
  "/app/investigate": { title: "Investigate", section: "cost diagnosis" },
  "/app/savings": { title: "Savings", section: "savings recommendations" },
  "/app/settings": { title: "Settings", section: "settings" },
};

function Placeholder({ title, section }: { title: string; section: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
      <div className="mx-auto inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500 ring-1 ring-inset ring-slate-600/10">
        Coming soon
      </div>
      <h2 className="mt-4 text-lg font-semibold text-slate-900">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
        This section is coming in a later phase. Connect your AI stack first — then
        your {section} will show up here.
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
            if ("comingSoon" in item && item.comingSoon) {
              return (
                <span
                  key={item.label}
                  className="flex cursor-not-allowed items-center justify-between rounded-lg px-3 py-2 text-sm font-medium text-slate-400"
                  title="Coming in a later phase"
                >
                  {item.label}
                  <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400 ring-1 ring-inset ring-slate-600/10">
                    Soon
                  </span>
                </span>
              );
            }
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href!}
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
        {/* Mobile section nav — the sidebar is desktop-only, so small screens get this strip. */}
        <nav className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-4 py-2 md:hidden" aria-label="App sections">
          {NAV.filter((item) => !("comingSoon" in item)).map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href!}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium",
                  active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <main className="flex-1 p-6 md:p-10">
          {PLACEHOLDERS[pathname] ? (
            <Placeholder
              title={PLACEHOLDERS[pathname].title}
              section={PLACEHOLDERS[pathname].section}
            />
          ) : (
            children
          )}
        </main>
      </div>
    </div>
  );
}
