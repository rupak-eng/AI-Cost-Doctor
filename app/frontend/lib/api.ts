/**
 * API client for the AI Cost Doctor backend.
 * Base URL: /api/v1. Configured via NEXT_PUBLIC_API_URL (default http://localhost:8000).
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const API_V1 = `${API_BASE}/api/v1`;

const ACCESS_TOKEN_KEY = "acd_access_token";
const REFRESH_TOKEN_KEY = "acd_refresh_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(access: string, refresh?: string | null): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACCESS_TOKEN_KEY, access);
  if (refresh) window.localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Fetch failed because the server could not be reached at all. */
export class ApiUnreachableError extends Error {
  constructor() {
    super(
      "The AI Cost Doctor API is unreachable. Make sure the backend is running " +
        `(${API_BASE}) and try again.`
    );
    this.name = "ApiUnreachableError";
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
  { auth = true }: { auth?: boolean } = {}
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (auth) {
    const token = getAccessToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  let res: Response;
  try {
    res = await fetch(`${API_V1}${path}`, { ...options, headers });
  } catch {
    throw new ApiUnreachableError();
  }
  if (!res.ok) {
    let detail = `Request failed with status ${res.status}.`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep generic detail */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Typed API surface (contract per specs/03-implementation-plan.md)
// ---------------------------------------------------------------------------

export interface PnlTenant {
  tenant_id: string;
  tenant_external_id: string;
  name: string;
  revenue_usd: number;
  ai_cost_usd: number;
  unpriced_events: number;
  margin_usd: number;
  status: "margin_killer" | "at_risk" | "healthy" | "unknown";
}

export interface PnlResponse {
  tenants: PnlTenant[];
  data_label: "demo" | "customer";
}

/** Backwards-compatible aliases for the Phase 2 names. */
export type DemoPnlTenant = PnlTenant;
export type DemoPnlResponse = PnlResponse;

export interface CostBreakdownItem {
  key: string;
  label: string;
  cost_usd: number;
  share_pct?: number;
}

export interface VolumeVsTokens {
  volume_change_pct?: number;
  tokens_change_pct?: number;
  note?: string;
  /** Dollar attribution of the cost change (recent 7d vs prior window). */
  volume_effect_usd?: number;
  token_intensity_effect_usd?: number;
  mix_effect_usd?: number;
  [k: string]: unknown;
}

export interface ExpensiveWorkflow {
  workflow?: string;
  name?: string;
  model?: string;
  cost_usd?: number;
  requests?: number;
  [k: string]: unknown;
}

export interface Recommendation {
  type?: string;
  title?: string;
  action: string;
  explanation?: string;
  est_savings_usd_mo: number;
  confidence: string;
  post_change_margin_usd?: number | null;
  disclaimer?: string;
  detail?: Record<string, unknown>;
}

export interface DemoInvestigateResponse {
  summary: string;
  tenant_name?: string;
  margin_usd?: number | null;
  drivers: { by_model: CostBreakdownItem[]; by_app: CostBreakdownItem[] };
  volume_vs_tokens: VolumeVsTokens;
  expensive_workflows: ExpensiveWorkflow[];
  recommendation: Recommendation | null;
  recommendations?: Recommendation[];
  disclaimer?: string;
  data_label: "demo" | "customer";
}

/** Backwards-compatible alias. */
export type InvestigateResponse = DemoInvestigateResponse;

/** Backend serializes Decimals as strings; normalize to numbers at the boundary. */
export function normalizePnlResponse(raw: PnlResponse): PnlResponse {
  return {
    ...raw,
    tenants: raw.tenants.map((t) => ({
      ...t,
      revenue_usd: Number(t.revenue_usd),
      ai_cost_usd: Number(t.ai_cost_usd),
      margin_usd: Number(t.margin_usd),
    })),
  };
}

export async function fetchDemoPnl(): Promise<PnlResponse> {
  const raw = await apiFetch<PnlResponse>("/demo/pnl", {}, { auth: false });
  return normalizePnlResponse(raw);
}

export async function fetchProjectPnl(projectId: string): Promise<PnlResponse> {
  const raw = await apiFetch<PnlResponse>(`/projects/${projectId}/pnl`);
  return normalizePnlResponse(raw);
}

/** Backend serializes Decimals as strings; normalize to numbers at the boundary. */
function normalizeInvestigateResponse(raw: DemoInvestigateResponse): InvestigateResponse {
  // Backend serializes Decimals as strings; normalize to numbers at the boundary.
  const num = (v: unknown): number => Number(v);
  // Backend driver items are {model|app, cost_usd, pct}; the UI reads {key, label, cost_usd, share_pct}.
  const normDriver = (d: CostBreakdownItem): CostBreakdownItem => {
    const raw_d = d as unknown as Record<string, unknown>;
    return {
      key: String(d.key ?? raw_d.model ?? raw_d.app ?? ""),
      label: String(d.label ?? raw_d.model ?? raw_d.app ?? ""),
      cost_usd: num(d.cost_usd),
      share_pct:
        d.share_pct != null ? num(d.share_pct) : raw_d.pct != null ? num(raw_d.pct) : undefined,
    };
  };
  return {
    ...raw,
    drivers: {
      by_model: raw.drivers.by_model.map(normDriver),
      by_app: raw.drivers.by_app.map(normDriver),
    },
    expensive_workflows: raw.expensive_workflows.map((w) => ({
      ...w,
      // Backend sends the application name as `app`; the table reads `workflow`/`name`.
      workflow: (() => {
        const v = w.workflow ?? w.name ?? (w as Record<string, unknown>).app;
        return v != null ? String(v) : undefined;
      })(),
      cost_usd: w.cost_usd != null ? num(w.cost_usd) : w.cost_usd,
    })),
    // Backend sends requests_delta_pct / avg_tokens_per_request_delta_pct / window_note;
    // the UI reads volume_change_pct / tokens_change_pct / note.
    volume_vs_tokens: (() => {
      const vvt = raw.volume_vs_tokens as unknown as Record<string, unknown>;
      const vol = vvt.volume_change_pct ?? vvt.requests_delta_pct;
      const tok = vvt.tokens_change_pct ?? vvt.avg_tokens_per_request_delta_pct;
      const note = vvt.note ?? vvt.window_note;
      return {
        ...raw.volume_vs_tokens,
        volume_change_pct: vol != null ? num(vol) : undefined,
        tokens_change_pct: tok != null ? num(tok) : undefined,
        note: note != null ? String(note) : undefined,
        volume_effect_usd:
          vvt.volume_effect_usd != null ? num(vvt.volume_effect_usd) : undefined,
        token_intensity_effect_usd:
          vvt.token_intensity_effect_usd != null ? num(vvt.token_intensity_effect_usd) : undefined,
        mix_effect_usd: vvt.mix_effect_usd != null ? num(vvt.mix_effect_usd) : undefined,
      };
    })(),
    recommendation: normalizeRecommendation(raw.recommendation),
    recommendations: (raw.recommendations ?? [])
      .map(normalizeRecommendation)
      .filter((r): r is Recommendation => r !== null),
  };
}

function normalizeRecommendation(
  rec: Recommendation | null | undefined
): Recommendation | null {
  if (!rec) return null;
  const num = (v: unknown): number => Number(v);
  return {
    ...rec,
    est_savings_usd_mo: num(rec.est_savings_usd_mo),
    post_change_margin_usd:
      rec.post_change_margin_usd != null ? num(rec.post_change_margin_usd) : null,
    // Backend sends lowercase ("medium"); display title case ("Medium").
    confidence: (rec.confidence ?? "").replace(/\b\w/g, (c) => c.toUpperCase()),
  };
}

// ---------------------------------------------------------------------------
// Investigate
// ---------------------------------------------------------------------------

export async function fetchDemoInvestigate(tenantId: string): Promise<InvestigateResponse> {
  const raw = await apiFetch<DemoInvestigateResponse>(
    "/demo/investigate",
    { method: "POST", body: JSON.stringify({ tenant_external_id: tenantId }) },
    { auth: false }
  );
  return normalizeInvestigateResponse(raw);
}

export async function fetchProjectInvestigate(
  projectId: string,
  tenantExternalId: string
): Promise<InvestigateResponse> {
  const raw = await apiFetch<DemoInvestigateResponse>(
    `/projects/${projectId}/investigate`,
    { method: "POST", body: JSON.stringify({ tenant_external_id: tenantExternalId }) }
  );
  return normalizeInvestigateResponse(raw);
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface AuthTokens {
  access_token: string;
  refresh_token?: string | null;
  token_type?: string;
}

export interface AuthUser {
  id?: string;
  email?: string;
  org?: { id?: string; name?: string };
  [k: string]: unknown;
}

export async function signup(email: string, password: string, orgName: string) {
  const res = await apiFetch<AuthTokens & { user?: AuthUser; org?: unknown }>(
    "/auth/signup",
    { method: "POST", body: JSON.stringify({ email, password, org_name: orgName }) },
    { auth: false }
  );
  if (res.access_token) setTokens(res.access_token, res.refresh_token ?? null);
  return res;
}

export async function login(email: string, password: string) {
  const res = await apiFetch<AuthTokens & { user?: AuthUser; org?: unknown }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    { auth: false }
  );
  if (res.access_token) setTokens(res.access_token, res.refresh_token ?? null);
  return res;
}

export async function fetchMe(): Promise<AuthUser> {
  return apiFetch<AuthUser>("/auth/me");
}

export function logout(): void {
  clearTokens();
}

export function formatUsd(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

// ---------------------------------------------------------------------------
// Projects (Phase 3)
// ---------------------------------------------------------------------------

export interface ProjectSummary {
  id: string;
  name: string;
}

/** Pull the project list out of GET /auth/me, tolerating missing/odd shapes. */
export function extractProjects(me: AuthUser): ProjectSummary[] {
  const raw = (me as { projects?: unknown }).projects;
  if (!Array.isArray(raw)) return [];
  const out: ProjectSummary[] = [];
  for (const p of raw) {
    if (p && typeof p === "object") {
      const rec = p as Record<string, unknown>;
      if (rec.id != null) {
        out.push({
          id: String(rec.id),
          name: typeof rec.name === "string" && rec.name ? rec.name : String(rec.id),
        });
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Project API keys (Phase 3)
// ---------------------------------------------------------------------------

export interface ApiKeyInfo {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  revoked_at?: string | null;
}

/** Returned once at creation — the only time the plaintext key is available. */
export interface ApiKeyCreated extends ApiKeyInfo {
  api_key: string;
}

export async function listApiKeys(projectId: string): Promise<ApiKeyInfo[]> {
  return apiFetch<ApiKeyInfo[]>(`/projects/${projectId}/api-keys`);
}

export async function createApiKey(projectId: string, name: string): Promise<ApiKeyCreated> {
  return apiFetch<ApiKeyCreated>(`/projects/${projectId}/api-keys`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function revokeApiKey(projectId: string, keyId: string): Promise<void> {
  await apiFetch<void>(`/projects/${projectId}/api-keys/${keyId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// CSV upload (Phase 3)
// ---------------------------------------------------------------------------

export interface CsvPreviewRow {
  row_number: number;
  valid: boolean;
  error?: string | null;
  tenant?: string | null;
  model?: string | null;
  provider?: string | null;
  cost_usd?: number | null;
  [k: string]: unknown;
}

export interface CsvUploadResponse {
  dry_run: boolean;
  rows_received: number;
  rows_valid: number;
  rows_invalid: number;
  /** Preview rows (dry run) — may be truncated to the first N rows by the server. */
  rows: CsvPreviewRow[];
  /** Commit mode: number of usage events ingested. */
  events_ingested?: number | null;
}

function parseApiError(res: Response): Promise<never> {
  return res
    .json()
    .then((body) => {
      const detail =
        body && typeof body.detail === "string"
          ? body.detail
          : `Request failed with status ${res.status}.`;
      throw new ApiError(res.status, detail);
    })
    .catch((e) => {
      if (e instanceof ApiError) throw e;
      throw new ApiError(res.status, `Request failed with status ${res.status}.`);
    });
}

/**
 * Upload a usage CSV for a project. `columnMap` maps canonical field names
 * (timestamp, provider, model, application, tenant, input_tokens, output_tokens,
 * cost_reported) to the CSV's header names; `revenues` maps tenant id → monthly
 * revenue in USD. With `dryRun=true` the server parses and validates without
 * ingesting.
 */
export async function uploadCsv(
  projectId: string,
  file: File,
  columnMap: Record<string, string>,
  revenues: Record<string, number> | null,
  dryRun: boolean
): Promise<CsvUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("project_id", projectId);
  form.append("column_map", JSON.stringify(columnMap));
  if (revenues) form.append("revenues", JSON.stringify(revenues));
  form.append("dry_run", String(dryRun));
  const token = getAccessToken();
  let res: Response;
  try {
    res = await fetch(`${API_V1}/integrations/csv/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
  } catch {
    throw new ApiUnreachableError();
  }
  if (!res.ok) await parseApiError(res);
  const raw = (await res.json()) as CsvUploadResponse;
  // Backend serializes Decimals as strings; normalize to numbers at the boundary.
  return {
    ...raw,
    rows: (raw.rows ?? []).map((r) => ({
      ...r,
      cost_usd: r.cost_usd != null ? Number(r.cost_usd) : r.cost_usd,
    })),
  };
}

// ---------------------------------------------------------------------------
// Provider integrations (Phase 4: OpenAI + Anthropic usage sync)
// ---------------------------------------------------------------------------

export type ProviderName = "openai" | "anthropic";

export interface ProviderCredentialInfo {
  id: string;
  provider: ProviderName;
  label: string | null;
  key_last4: string;
  status: "active" | "error";
  last_sync_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface ProviderSyncSummary {
  credential_id: string;
  provider: ProviderName;
  project_id: string;
  days_back: number;
  events_written: number;
  cost_reports_written: number;
  unpriced_models: string[];
}

export interface ProviderSyncStatus {
  id: string;
  provider: ProviderName;
  status: "active" | "error";
  last_sync_at: string | null;
  last_error: string | null;
}

/** Validate + store a provider Admin API key. The key is never returned or retained. */
export async function connectProvider(
  provider: ProviderName,
  apiKey: string,
  label?: string | null
): Promise<ProviderCredentialInfo> {
  return apiFetch<ProviderCredentialInfo>("/integrations/providers", {
    method: "POST",
    body: JSON.stringify({ provider, api_key: apiKey, label: label ?? null }),
  });
}

export async function listProviderCredentials(): Promise<ProviderCredentialInfo[]> {
  return apiFetch<ProviderCredentialInfo[]>("/integrations/providers");
}

export async function disconnectProvider(credentialId: string): Promise<void> {
  await apiFetch<void>(`/integrations/providers/${credentialId}`, { method: "DELETE" });
}

export async function syncProvider(
  credentialId: string,
  projectId: string,
  daysBack: number
): Promise<ProviderSyncSummary> {
  return apiFetch<ProviderSyncSummary>(
    `/integrations/providers/${credentialId}/sync?project_id=${encodeURIComponent(projectId)}`,
    { method: "POST", body: JSON.stringify({ days_back: daysBack }) }
  );
}

export async function getProviderSyncStatus(
  credentialId: string
): Promise<ProviderSyncStatus> {
  return apiFetch<ProviderSyncStatus>(`/integrations/providers/${credentialId}/sync-status`);
}

// ---------------------------------------------------------------------------
// Project dashboard (Phase 5)
// ---------------------------------------------------------------------------

export interface DashboardTrendPoint {
  date: string; // YYYY-MM-DD (UTC)
  cost_usd: number;
  requests: number;
}

export interface DashboardModelRow {
  provider: string;
  model: string;
  cost_usd: number;
  requests: number;
  share_pct: number;
}

export interface DashboardApplicationRow {
  application: string;
  cost_usd: number;
  requests: number;
  share_pct: number;
}

export interface DashboardTenantRow {
  tenant_external_id: string | null;
  tenant_name: string | null;
  cost_usd: number;
  requests: number;
}

export interface DashboardResponse {
  data_label: "customer";
  days: number;
  total_cost_usd: number;
  total_requests: number;
  unpriced_events: number;
  cost_basis: "calculated";
  trend: DashboardTrendPoint[];
  by_model: DashboardModelRow[];
  by_application: DashboardApplicationRow[];
  top_tenants: DashboardTenantRow[];
}

export type DashboardDays = 7 | 30 | 90;

/** Backend serializes Decimals as strings; normalize to numbers at the boundary. */
function normalizeDashboardResponse(raw: DashboardResponse): DashboardResponse {
  const num = (v: unknown): number => Number(v);
  return {
    ...raw,
    total_cost_usd: num(raw.total_cost_usd),
    trend: raw.trend.map((p) => ({ ...p, cost_usd: num(p.cost_usd) })),
    by_model: raw.by_model.map((r) => ({ ...r, cost_usd: num(r.cost_usd), share_pct: num(r.share_pct) })),
    by_application: raw.by_application.map((r) => ({ ...r, cost_usd: num(r.cost_usd), share_pct: num(r.share_pct) })),
    top_tenants: raw.top_tenants.map((r) => ({ ...r, cost_usd: num(r.cost_usd) })),
  };
}

export async function fetchProjectDashboard(
  projectId: string,
  days: DashboardDays = 30
): Promise<DashboardResponse> {
  const raw = await apiFetch<DashboardResponse>(
    `/projects/${projectId}/dashboard?days=${days}`
  );
  return normalizeDashboardResponse(raw);
}

// ---------------------------------------------------------------------------
// Anomaly detection (Phase 6)
// ---------------------------------------------------------------------------

export type AnomalyDetector = "spend_spike" | "new_expensive_model" | "margin_killer_emergence";
export type AnomalySeverity = "critical" | "warning" | "info";
export type AnomalyStatus = "open" | "acknowledged" | "investigated" | "resolved" | "dismissed";

export interface Anomaly {
  id: string;
  detector: AnomalyDetector | null;
  dimension: string;
  dimension_value: string | null;
  tenant_name: string | null;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  detected_at: string;
  baseline_usd: number | null;
  observed_usd: number | null;
  change_pct: number | null;
  abs_delta_usd: number | null;
  title: string;
  detail: string;
  evidence: Record<string, unknown>;
  investigate_tenant_external_id: string | null;
}

export interface AnomaliesResponse {
  data_label: "customer";
  days: number;
  anomalies: Anomaly[];
  unread_count: number;
}

/** Backend serializes Decimals as strings; normalize to numbers at the boundary. */
function normalizeAnomaly(raw: Anomaly): Anomaly {
  const num = (v: unknown): number | null => (v == null ? null : Number(v));
  return {
    ...raw,
    baseline_usd: num(raw.baseline_usd),
    observed_usd: num(raw.observed_usd),
    change_pct: num(raw.change_pct),
    abs_delta_usd: num(raw.abs_delta_usd),
  };
}

export async function fetchProjectAnomalies(
  projectId: string,
  days: DashboardDays = 30
): Promise<AnomaliesResponse> {
  const raw = await apiFetch<AnomaliesResponse>(
    `/projects/${projectId}/anomalies?days=${days}`
  );
  return { ...raw, anomalies: raw.anomalies.map(normalizeAnomaly) };
}

export async function acknowledgeAnomaly(
  projectId: string,
  anomalyId: string
): Promise<Anomaly> {
  const raw = await apiFetch<Anomaly>(
    `/projects/${projectId}/anomalies/${anomalyId}/acknowledge`,
    { method: "POST" }
  );
  return normalizeAnomaly(raw);
}

/* ------------------------------------------------------------------ */
/* Billing (Phase 8)                                                   */
/* ------------------------------------------------------------------ */

export type PlanName = "free" | "starter" | "growth";

export interface PlanLimits {
  display_name: string;
  monthly_price_usd: number;
  max_projects: number;
  events_per_month: number;
  retention_days: number;
}

export interface BillingStatus {
  plan: PlanName;
  effective_plan: PlanName;
  subscription_status: string | null;
  trial_active: boolean;
  trial_days_left: number | null;
  trial_ends_at: string | null;
  has_paid_access: boolean;
  stripe_customer_id: string | null;
  limits: PlanLimits;
  projects_count: number;
  events_this_month: number;
  events_over_limit: boolean;
  stripe_configured: boolean;
  data_label: string;
}

export interface CheckoutResponse {
  url: string;
  session_id: string;
  reused: boolean;
}

export interface PortalResponse {
  url: string;
}

export const PLAN_CATALOG: Record<Exclude<PlanName, "free">, {
  name: string;
  price: string;
  blurb: string;
  features: string[];
}> = {
  starter: {
    name: "Starter",
    price: "$49/mo",
    blurb: "For a single product getting AI spend under control.",
    features: ["1 project", "1M events / month", "30-day retention", "Tenant P&L & margin killers", "Anomaly alerts"],
  },
  growth: {
    name: "Growth",
    price: "$199/mo",
    blurb: "For teams scaling AI across products and customers.",
    features: ["5 projects", "10M events / month", "12-month retention", "Everything in Starter", "Priority support"],
  },
};

export async function fetchBillingStatus(): Promise<BillingStatus> {
  return apiFetch<BillingStatus>("/billing/status");
}

export async function createCheckoutSession(plan: Exclude<PlanName, "free">): Promise<CheckoutResponse> {
  return apiFetch<CheckoutResponse>("/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
}

export async function createPortalSession(): Promise<PortalResponse> {
  return apiFetch<PortalResponse>("/billing/portal", { method: "POST" });
}
