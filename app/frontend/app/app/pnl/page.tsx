"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import PnlView from "../../../components/pnl";
import ProjectSelector from "../../../components/project-selector";
import { ApiErrorNotice } from "../../../components/ui";
import { PnlResponse, fetchProjectPnl } from "../../../lib/api";
import { useProjects } from "../../../lib/project";

export default function AppPnlPage() {
  const projects = useProjects();
  const projectId = projects.selected?.id ?? null;
  const [data, setData] = useState<PnlResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!projectId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetchProjectPnl(projectId)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    if (!projects.loading) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.loading, projectId]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <p className="text-sm text-slate-600">
          Customer profitability for{" "}
          <span className="font-semibold text-slate-900">
            {projects.selected?.name ?? "your project"}
          </span>
          .
        </p>
        <ProjectSelector state={projects} />
      </div>

      {projects.error && <ApiErrorNotice error={projects.error} onRetry={projects.reload} />}

      {!projects.loading && !projects.error && !projects.selected && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <h2 className="text-lg font-semibold text-slate-900">No project found</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
            We couldn&apos;t find a project on your account. Try signing out and
            back in, or contact support.
          </p>
        </div>
      )}

      {!projects.error && projects.selected && (
        <PnlView
          demo={false}
          loading={projects.loading || loading}
          error={error}
          onRetry={load}
          tenants={data?.tenants ?? []}
          investigateHref={(tenantExternalId) =>
            `/app/pnl/investigate?tenant=${encodeURIComponent(tenantExternalId)}`
          }
          emptyState={
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-100 text-xl font-bold text-indigo-700">
                $
              </div>
              <h2 className="mt-4 text-lg font-semibold text-slate-900">
                No usage data yet
              </h2>
              <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
                Once usage events are flowing, this view shows per-customer AI unit
                economics — revenue, AI cost, and gross AI margin per customer —
                with margin killers flagged for investigation.
              </p>
              <Link
                href="/app/connect"
                className="mt-6 inline-flex rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                Connect your AI stack →
              </Link>
            </div>
          }
        />
      )}
    </div>
  );
}
