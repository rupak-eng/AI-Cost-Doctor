"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Anomaly,
  acknowledgeAnomaly,
} from "../lib/api";
import { cn } from "./cn";

const DETECTOR_LABELS: Record<string, string> = {
  spend_spike: "Spend spike",
  new_expensive_model: "New model",
  margin_killer_emergence: "Margin killer",
};

const SEVERITY_STYLE: Record<string, { dot: string; badge: string; label: string }> = {
  critical: {
    dot: "bg-red-500",
    badge: "bg-red-100 text-red-800",
    label: "Critical",
  },
  warning: {
    dot: "bg-amber-500",
    badge: "bg-amber-100 text-amber-800",
    label: "Warning",
  },
  info: {
    dot: "bg-sky-500",
    badge: "bg-sky-100 text-sky-800",
    label: "Info",
  },
};

function AnomalyCard({
  anomaly,
  projectId,
  onAcknowledged,
}: {
  anomaly: Anomaly;
  projectId: string;
  onAcknowledged: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const style = SEVERITY_STYLE[anomaly.severity] ?? SEVERITY_STYLE.info;
  const detectorLabel = anomaly.detector
    ? DETECTOR_LABELS[anomaly.detector] ?? anomaly.detector
    : "Anomaly";
  const detected = new Date(anomaly.detected_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  const acknowledge = async () => {
    setBusy(true);
    try {
      await acknowledgeAnomaly(projectId, anomaly.id);
      onAcknowledged(anomaly.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <span className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", style.dot)} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", style.badge)}>
            {style.label}
          </span>
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {detectorLabel}
          </span>
          {anomaly.status !== "open" && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
              {anomaly.status}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-sm font-semibold text-slate-900">{anomaly.title}</p>
        <p className="mt-1 text-sm text-slate-600">{anomaly.detail}</p>
        <p className="mt-2 text-xs text-slate-400">Detected {detected}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {anomaly.investigate_tenant_external_id && (
            <Link
              href={`/app/pnl/investigate?tenant=${encodeURIComponent(
                anomaly.investigate_tenant_external_id
              )}`}
              className="inline-flex rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              Investigate →
            </Link>
          )}
          {anomaly.status === "open" && (
            <button
              onClick={acknowledge}
              disabled={busy}
              className="inline-flex rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {busy ? "Acknowledging…" : "Acknowledge"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Anomaly feed for the Overview dashboard: severity-ordered cards with an
 * unread badge, investigate deep-links, and acknowledge actions.
 */
export default function AnomaliesFeed({
  projectId,
  anomalies,
  unreadCount,
  days,
  onAcknowledged,
}: {
  projectId: string;
  anomalies: Anomaly[];
  unreadCount: number;
  days: number;
  onAcknowledged: (id: string) => void;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-900">Anomalies</h2>
          {unreadCount > 0 && (
            <span className="rounded-full bg-red-600 px-2 py-0.5 text-xs font-bold text-white">
              {unreadCount} new
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500">Deterministic checks, last {days} days</p>
      </div>
      {anomalies.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500">
          No anomalies in the last {days} days. Cost spikes, expensive new models,
          and margin-killer crossings will surface here.
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          {anomalies.slice(0, 10).map((a) => (
            <AnomalyCard
              key={a.id}
              anomaly={a}
              projectId={projectId}
              onAcknowledged={onAcknowledged}
            />
          ))}
        </div>
      )}
      <p className="mt-4 text-xs text-slate-400">
        Figures are computed from calculated cost (deterministic catalog pricing),
        never from provider-reported totals.
      </p>
    </div>
  );
}
