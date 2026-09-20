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

export interface DemoPnlTenant {
  tenant_id: string;
  tenant_external_id: string;
  name: string;
  revenue_usd: number;
  ai_cost_usd: number;
  margin_usd: number;
  status: "margin_killer" | "at_risk" | "healthy";
}

export interface DemoPnlResponse {
  tenants: DemoPnlTenant[];
  data_label: "demo";
}

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
  action: string;
  est_savings_usd_mo: number;
  confidence: string;
  post_change_margin_usd: number;
}

export interface DemoInvestigateResponse {
  summary: string;
  drivers: { by_model: CostBreakdownItem[]; by_app: CostBreakdownItem[] };
  volume_vs_tokens: VolumeVsTokens;
  expensive_workflows: ExpensiveWorkflow[];
  recommendation: Recommendation;
  data_label: "demo";
}

export async function fetchDemoPnl(): Promise<DemoPnlResponse> {
  const raw = await apiFetch<DemoPnlResponse>("/demo/pnl", {}, { auth: false });
  // Backend serializes Decimals as strings; normalize to numbers at the boundary.
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

export async function fetchDemoInvestigate(tenantId: string): Promise<DemoInvestigateResponse> {
  const raw = await apiFetch<DemoInvestigateResponse>(
    "/demo/investigate",
    { method: "POST", body: JSON.stringify({ tenant_external_id: tenantId }) },
    { auth: false }
  );
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
      };
    })(),
    recommendation: {
      ...raw.recommendation,
      est_savings_usd_mo: num(raw.recommendation.est_savings_usd_mo),
      post_change_margin_usd: num(raw.recommendation.post_change_margin_usd),
      // Backend sends lowercase ("medium"); display title case ("Medium").
      confidence: raw.recommendation.confidence.replace(/\b\w/g, (c) => c.toUpperCase()),
    },
  };
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
