"use client";

import { useCallback, useEffect, useState } from "react";
import { extractProjects, fetchMe, ProjectSummary } from "./api";

export interface ProjectsState {
  projects: ProjectSummary[];
  /** Selected project (first project by default; null while loading or none). */
  selected: ProjectSummary | null;
  select: (id: string) => void;
  loading: boolean;
  error: Error | null;
  reload: () => void;
}

/**
 * Resolves the signed-in user's projects (via GET /auth/me) and tracks the
 * selected one. v0.1: defaults to the first project; a selector appears when
 * there is more than one.
 */
export function useProjects(): ProjectsState {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchMe()
      .then((me) => {
        const list = extractProjects(me);
        setProjects(list);
        setSelectedId((prev) =>
          prev && list.some((p) => p.id === prev) ? prev : (list[0]?.id ?? null)
        );
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e : new Error("Couldn't load projects."))
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const select = useCallback(
    (id: string) => {
      if (projects.some((p) => p.id === id)) setSelectedId(id);
    },
    [projects]
  );

  return {
    projects,
    selected: projects.find((p) => p.id === selectedId) ?? null,
    select,
    loading,
    error,
    reload,
  };
}
