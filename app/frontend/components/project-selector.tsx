"use client";

import { ProjectsState } from "../lib/project";

/** Project dropdown, shown only when the org has more than one project. */
export default function ProjectSelector({ state }: { state: ProjectsState }) {
  if (state.loading || state.projects.length <= 1) return null;
  return (
    <label className="inline-flex items-center gap-2 text-sm text-slate-600">
      Project
      <select
        value={state.selected?.id ?? ""}
        onChange={(e) => state.select(e.target.value)}
        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-900"
      >
        {state.projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}
