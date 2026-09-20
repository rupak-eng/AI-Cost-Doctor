"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import ProjectSelector from "../../../components/project-selector";
import { ApiErrorNotice } from "../../../components/ui";
import {
  ApiKeyCreated,
  ApiKeyInfo,
  CsvUploadResponse,
  createApiKey,
  formatUsd,
  listApiKeys,
  revokeApiKey,
  uploadCsv,
} from "../../../lib/api";
import { useProjects } from "../../../lib/project";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    /* fall through to legacy path */
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// ---------------------------------------------------------------------------
// Event API section
// ---------------------------------------------------------------------------

const EVENT_PAYLOAD_EXAMPLE = `POST /api/v1/ingest/events
X-API-Key: <your-project-api-key>
Content-Type: application/json

{
  "events": [
    {
      "timestamp": "2026-09-21T10:00:00Z",
      "provider": "openai",
      "model": "gpt-4o",
      "application": "support-copilot",
      "tenant": "acme-corp",
      "input_tokens": 1200,
      "output_tokens": 340,
      "cost_reported": 0.0042
    }
  ]
}`;

function EventApiSection({ projectId }: { projectId: string }) {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    listApiKeys(projectId)
      .then(setKeys)
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const handleCreate = async () => {
    const trimmed = name.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    setError(null);
    try {
      const key = await createApiKey(projectId, trimmed);
      setCreated(key);
      setCopied(false);
      setName("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Couldn't create the API key."));
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    setRevokingId(keyId);
    setError(null);
    try {
      await revokeApiKey(projectId, keyId);
      setConfirmRevokeId(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Couldn't revoke the API key."));
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 md:p-8">
      <h2 className="text-xl font-bold tracking-tight text-slate-900">Event API</h2>
      <p className="mt-2 max-w-3xl text-sm text-slate-600">
        Stream usage events straight from your application. Create a per-project API
        key, then <code className="rounded bg-slate-100 px-1 text-xs">POST</code> batches of
        events with an <code className="rounded bg-slate-100 px-1 text-xs">X-API-Key</code> header.
        Each event carries 8 fields:
      </p>

      <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs leading-relaxed text-slate-100">
        {EVENT_PAYLOAD_EXAMPLE}
      </pre>
      <p className="mt-2 text-xs text-slate-500">
        <code className="rounded bg-slate-100 px-1">cost_reported</code> is optional: when
        present we use your reported cost, otherwise we compute cost from tokens × the
        model&apos;s price. Timestamps are ISO-8601 UTC.
      </p>

      {/* Create key */}
      <div className="mt-6">
        <h3 className="text-sm font-semibold text-slate-900">Create an API key</h3>
        <div className="mt-2 flex max-w-md gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
            }}
            placeholder="e.g. production"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400"
          />
          <button
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {creating ? "Creating…" : "Create key"}
          </button>
        </div>
      </div>

      {/* Show-once box */}
      {created && (
        <div className="mt-4 max-w-2xl rounded-lg border border-amber-300 bg-amber-50 p-4">
          <p className="text-sm font-semibold text-amber-900">
            ⚠ Copy it now — this key won&apos;t be shown again.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 truncate rounded-md bg-white px-3 py-2 font-mono text-sm text-slate-900 ring-1 ring-inset ring-slate-200">
              {created.api_key}
            </code>
            <button
              onClick={async () => setCopied(await copyText(created.api_key))}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              {copied ? "Copied ✓" : "Copy"}
            </button>
          </div>
        </div>
      )}

      {/* Key list */}
      <div className="mt-6">
        <h3 className="text-sm font-semibold text-slate-900">Your API keys</h3>
        {loading && <p className="mt-2 text-sm text-slate-500">Loading keys…</p>}
        {error && (
          <div className="mt-2">
            <ApiErrorNotice error={error} onRetry={load} />
          </div>
        )}
        {!loading && !error && keys.length === 0 && (
          <p className="mt-2 text-sm text-slate-500">No API keys yet. Create one above to get started.</p>
        )}
        {!loading && !error && keys.length > 0 && (
          <div className="mt-2 overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Key prefix</th>
                  <th className="px-4 py-2 font-medium">Created</th>
                  <th className="px-4 py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {keys.map((k) => (
                  <tr key={k.id}>
                    <td className="px-4 py-2.5 font-medium text-slate-900">{k.name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-600">{k.key_prefix}…</td>
                    <td className="px-4 py-2.5 text-slate-600">{fmtDate(k.created_at)}</td>
                    <td className="px-4 py-2.5 text-right">
                      {confirmRevokeId === k.id ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="text-xs text-slate-600">Revoke this key?</span>
                          <button
                            onClick={() => handleRevoke(k.id)}
                            disabled={revokingId === k.id}
                            className="rounded-md bg-red-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                          >
                            {revokingId === k.id ? "Revoking…" : "Yes, revoke"}
                          </button>
                          <button
                            onClick={() => setConfirmRevokeId(null)}
                            className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                          >
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button
                          onClick={() => setConfirmRevokeId(k.id)}
                          className="rounded-md px-2.5 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Keys are stored hashed and can be revoked at any time. Revoked keys stop
          authenticating immediately.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// CSV upload section
// ---------------------------------------------------------------------------

interface CanonicalField {
  key: string;
  label: string;
  required: boolean;
  hint: string;
}

const CANONICAL_FIELDS: CanonicalField[] = [
  { key: "timestamp", label: "Timestamp", required: true, hint: "When the usage happened (ISO-8601)." },
  { key: "provider", label: "Provider", required: false, hint: "e.g. openai, anthropic." },
  { key: "model", label: "Model", required: false, hint: "e.g. gpt-4o. Needed to compute cost from tokens." },
  { key: "application", label: "Application", required: false, hint: "Which app or workflow generated the usage." },
  { key: "tenant", label: "Tenant", required: true, hint: "Customer id — powers the per-customer P&L." },
  { key: "input_tokens", label: "Input tokens", required: false, hint: "Prompt tokens." },
  { key: "output_tokens", label: "Output tokens", required: false, hint: "Completion tokens." },
  { key: "cost_reported", label: "Reported cost", required: false, hint: "USD cost, if your export already includes it." },
];

const FIELD_ALIASES: Record<string, string[]> = {
  timestamp: ["timestamp", "time", "date", "datetime", "createdat", "eventtime", "occurredat", "ts"],
  provider: ["provider", "vendor", "platform"],
  model: ["model", "modelname", "llm", "engine", "modelid"],
  application: ["application", "app", "applicationname", "service", "workflow"],
  tenant: ["tenant", "tenantid", "customer", "customerid", "client", "clientid", "account", "accountid", "org", "orgid"],
  input_tokens: ["inputtokens", "prompttokens", "tokensin", "input"],
  output_tokens: ["outputtokens", "completiontokens", "tokensout", "output"],
  cost_reported: ["costreported", "cost", "costusd", "totalcost", "totalcostusd", "amount", "spend", "price", "total"],
};

function normalizeHeader(h: string): string {
  return h.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** Guess which canonical field each CSV header maps to. */
function autoMap(headers: string[]): Record<string, string> {
  const used = new Set<string>();
  const map: Record<string, string> = {};
  const tryField = (field: string) => {
    for (const h of headers) {
      if (used.has(h)) continue;
      if (FIELD_ALIASES[field]?.includes(normalizeHeader(h))) {
        map[field] = h;
        used.add(h);
        return;
      }
    }
  };
  // Required fields first so they win on ambiguous headers.
  for (const f of CANONICAL_FIELDS.filter((f) => f.required)) tryField(f.key);
  for (const f of CANONICAL_FIELDS.filter((f) => !f.required)) tryField(f.key);
  return map;
}

/** Quote-aware split of a single CSV line. */
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQuotes) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      out.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

function CsvUploadSection({ projectId }: { projectId: string }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [revenuesText, setRevenuesText] = useState("");
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<CsvUploadResponse | null>(null);
  const [imported, setImported] = useState<CsvUploadResponse | null>(null);

  const reset = () => {
    setFile(null);
    setHeaders([]);
    setMapping({});
    setPreview(null);
    setImported(null);
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleFile = (f: File | null) => {
    reset();
    if (!f) return;
    setFile(f);
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "");
      const firstLine = text.split(/\r?\n/)[0] ?? "";
      const cols = splitCsvLine(firstLine).filter((c) => c.length > 0);
      if (cols.length === 0) {
        setError("Couldn't read a header row from this file. Make sure it's a valid CSV.");
        return;
      }
      setHeaders(cols);
      setMapping(autoMap(cols));
    };
    reader.onerror = () => setError("Couldn't read that file.");
    // Header row is at the top — 64KB is plenty.
    reader.readAsText(f.slice(0, 64 * 1024));
  };

  const parseRevenues = (): { ok: true; value: Record<string, number> | null } | { ok: false; message: string } => {
    const t = revenuesText.trim();
    if (!t) return { ok: true, value: null };
    let parsed: unknown;
    try {
      parsed = JSON.parse(t);
    } catch {
      return { ok: false, message: "Revenues must be valid JSON, e.g. {\"acme-corp\": 1200}." };
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, message: "Revenues must be a JSON object mapping tenant id → monthly revenue in USD." };
    }
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      const n = Number(v);
      if (!Number.isFinite(n) || n < 0) {
        return { ok: false, message: `Revenue for "${k}" must be a non-negative number.` };
      }
      out[k] = n;
    }
    return { ok: true, value: out };
  };

  const runUpload = async (dryRun: boolean) => {
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    if (!mapping.timestamp || !mapping.tenant) {
      setError("Map the required fields (Timestamp, Tenant) before continuing.");
      return;
    }
    const rev = parseRevenues();
    if (!rev.ok) {
      setError(rev.message);
      return;
    }
    const columnMap = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v));
    setBusy(dryRun ? "preview" : "import");
    setError(null);
    try {
      const res = await uploadCsv(projectId, file, columnMap, rev.value, dryRun);
      if (dryRun) {
        setPreview(res);
      } else {
        setImported(res);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setBusy(null);
    }
  };

  const previewRows = preview?.rows.slice(0, 25) ?? [];
  const ingestedCount = imported?.events_ingested ?? imported?.rows_valid ?? 0;

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 md:p-8">
      <h2 className="text-xl font-bold tracking-tight text-slate-900">CSV upload</h2>
      <p className="mt-2 max-w-3xl text-sm text-slate-600">
        Drop in a billing or usage export. Map your columns to our canonical fields,
        optionally add per-customer revenue, then preview the dry run before importing.
        Nothing is ingested until you press <span className="font-semibold">Import</span>.
      </p>

      {/* File picker */}
      <div className="mt-6">
        <label className="text-sm font-semibold text-slate-900" htmlFor="csv-file">
          1. Choose your CSV file
        </label>
        <div className="mt-2 flex items-center gap-3">
          <input
            id="csv-file"
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            className="text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-600 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-indigo-700"
          />
          {file && (
            <button onClick={reset} className="text-sm font-medium text-slate-500 hover:text-slate-800">
              Clear
            </button>
          )}
        </div>
        {file && headers.length > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            <span className="font-medium text-slate-700">{file.name}</span> — {headers.length} columns detected.
          </p>
        )}
      </div>

      {/* Column mapping */}
      {file && headers.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-900">2. Map your columns</h3>
          <p className="mt-1 text-xs text-slate-500">
            We pre-filled guesses from your header row — adjust as needed. At least one
            cost signal is needed: token counts with a model, or a reported cost column.
          </p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {CANONICAL_FIELDS.map((f) => (
              <div key={f.key} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <label htmlFor={`map-${f.key}`} className="text-sm font-medium text-slate-800">
                    {f.label}
                  </label>
                  <span
                    className={
                      f.required
                        ? "rounded-md bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 ring-1 ring-inset ring-red-600/20"
                        : "rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500 ring-1 ring-inset ring-slate-600/10"
                    }
                  >
                    {f.required ? "Required" : "Optional"}
                  </span>
                </div>
                <select
                  id={`map-${f.key}`}
                  value={mapping[f.key] ?? ""}
                  onChange={(e) =>
                    setMapping((m) => ({ ...m, [f.key]: e.target.value }))
                  }
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900"
                >
                  <option value="">— not mapped —</option>
                  {headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-slate-500">{f.hint}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Revenues */}
      {file && headers.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-900">
            3. Per-customer revenue <span className="font-normal text-slate-500">(optional)</span>
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            Revenue is needed for gross AI margin and margin-killer detection. Paste a
            JSON object mapping tenant id → monthly revenue in USD.
          </p>
          <textarea
            value={revenuesText}
            onChange={(e) => setRevenuesText(e.target.value)}
            placeholder={'{\n  "acme-corp": 1200,\n  "globex": 800\n}'}
            rows={4}
            spellCheck={false}
            className="mt-2 w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs text-slate-900 placeholder:text-slate-400"
          />
        </div>
      )}

      {/* Actions */}
      {file && headers.length > 0 && !imported && (
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            onClick={() => runUpload(true)}
            disabled={busy !== null}
            className="rounded-lg border border-indigo-600 bg-white px-4 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "preview" ? "Previewing…" : "Preview (dry run)"}
          </button>
          {preview && preview.rows_valid > 0 && (
            <button
              onClick={() => runUpload(false)}
              disabled={busy !== null}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy === "import" ? "Importing…" : `Import ${preview.rows_valid.toLocaleString()} rows`}
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="mt-4 max-w-2xl rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">
          {error}
        </div>
      )}

      {/* Dry-run preview */}
      {preview && !imported && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-900">Dry-run preview</h3>
          <dl className="mt-2 grid max-w-xl grid-cols-3 gap-3">
            <div className="rounded-lg bg-slate-50 p-3 text-center">
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Rows parsed</dt>
              <dd className="mt-1 text-xl font-bold tabular-nums text-slate-900">{preview.rows_received.toLocaleString()}</dd>
            </div>
            <div className="rounded-lg bg-emerald-50 p-3 text-center">
              <dt className="text-xs font-medium uppercase tracking-wide text-emerald-700">Valid</dt>
              <dd className="mt-1 text-xl font-bold tabular-nums text-emerald-800">{preview.rows_valid.toLocaleString()}</dd>
            </div>
            <div className="rounded-lg bg-red-50 p-3 text-center">
              <dt className="text-xs font-medium uppercase tracking-wide text-red-600">Invalid</dt>
              <dd className="mt-1 text-xl font-bold tabular-nums text-red-700">{preview.rows_invalid.toLocaleString()}</dd>
            </div>
          </dl>
          {previewRows.length > 0 && (
            <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 font-medium">Row</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Tenant</th>
                    <th className="px-3 py-2 font-medium">Model</th>
                    <th className="px-3 py-2 font-medium">Computed cost</th>
                    <th className="px-3 py-2 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {previewRows.map((r) => (
                    <tr key={r.row_number}>
                      <td className="px-3 py-2 tabular-nums text-slate-500">{r.row_number}</td>
                      <td className="px-3 py-2">
                        <span
                          className={
                            r.valid
                              ? "rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20"
                              : "rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 ring-1 ring-inset ring-red-600/20"
                          }
                        >
                          {r.valid ? "Valid" : "Invalid"}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-medium text-slate-900">{r.tenant ?? "—"}</td>
                      <td className="px-3 py-2 text-slate-600">{r.model ?? "—"}</td>
                      <td className="px-3 py-2 tabular-nums text-slate-900">
                        {r.cost_usd != null ? formatUsd(r.cost_usd) : "—"}
                      </td>
                      <td className="px-3 py-2 text-xs text-red-700">{r.error ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {preview.rows_received > previewRows.length && (
            <p className="mt-2 text-xs text-slate-500">
              Showing the first {previewRows.length} of {preview.rows_received.toLocaleString()} rows.
            </p>
          )}
        </div>
      )}

      {/* Import success */}
      {imported && (
        <div className="mt-6 rounded-lg border border-emerald-200 bg-emerald-50 p-6">
          <h3 className="text-lg font-semibold text-emerald-900">Import complete ✓</h3>
          <p className="mt-1 text-sm text-emerald-800">
            Ingested <span className="font-bold tabular-nums">{ingestedCount.toLocaleString()}</span>{" "}
            usage events into your project.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link
              href="/app/pnl"
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              View your Customer P&L →
            </Link>
            <button
              onClick={reset}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Upload another file
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ConnectPage() {
  const projects = useProjects();
  const projectId = projects.selected?.id ?? null;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Connect</h1>
          <p className="mt-1 text-sm text-slate-600">
            Get your usage data flowing. Upload a CSV export or stream events via the
            API — your Customer P&L appears as soon as data lands.
          </p>
        </div>
        <ProjectSelector state={projects} />
      </div>

      {projects.loading && <p className="text-sm text-slate-500">Loading project…</p>}
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

      {!projects.error && projectId && (
        <div className="space-y-8">
          <EventApiSection key={`events-${projectId}`} projectId={projectId} />
          <CsvUploadSection key={`csv-${projectId}`} projectId={projectId} />
        </div>
      )}
    </div>
  );
}
