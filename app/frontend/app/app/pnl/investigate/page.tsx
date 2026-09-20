"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import InvestigateView from "../../../../components/investigate-view";
import ProjectSelector from "../../../../components/project-selector";
import { ApiErrorNotice } from "../../../../components/ui";
import { InvestigateResponse, fetchProjectInvestigate } from "../../../../lib/api";
import { useProjects } from "../../../../lib/project";

function InvestigateContent() {
  const params = useSearchParams();
  const tenantId = params.get("tenant") ?? "";
  const projects = useProjects();
  const projectId = projects.selected?.id ?? null;
  const [data, setData] = useState<InvestigateResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!projectId || !tenantId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetchProjectInvestigate(projectId, tenantId)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!projects.loading) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.loading, projectId, tenantId]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-end">
        <ProjectSelector state={projects} />
      </div>

      {projects.error && (
        <div className="mb-6">
          <ApiErrorNotice error={projects.error} onRetry={projects.reload} />
        </div>
      )}

      {!projects.loading && !projects.error && !projects.selected && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <h2 className="text-lg font-semibold text-slate-900">No project found</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
            We couldn&apos;t find a project on your account. Try signing out and
            back in, or contact support.
          </p>
        </div>
      )}

      {projects.selected && (
        <InvestigateView
          demo={false}
          tenantId={tenantId}
          loading={projects.loading || loading}
          error={error}
          onRetry={load}
          data={data}
          backHref="/app/pnl"
          backLabel="Back to Customer P&L"
        />
      )}
    </div>
  );
}

export default function AppInvestigatePage() {
  return (
    <Suspense fallback={<div className="p-12 text-slate-500">Loading…</div>}>
      <InvestigateContent />
    </Suspense>
  );
}
