// Thin, typed client for the Prism REST API.

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

let workspaceId: string | null = localStorageGet("prism.workspace");

function localStorageGet(k: string): string | null {
  try {
    return window.localStorage.getItem(k);
  } catch {
    return null;
  }
}

export function setWorkspace(id: string | null) {
  workspaceId = id;
  try {
    if (id) window.localStorage.setItem("prism.workspace", id);
    else window.localStorage.removeItem("prism.workspace");
  } catch {
    /* storage unavailable */
  }
}

type Body = Record<string, unknown> | unknown[] | FormData | undefined;

export async function api<T = unknown>(
  method: string,
  path: string,
  body?: Body,
  opts: { raw?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { "X-Prism-CSRF": "1", Accept: "application/json" };
  if (workspaceId) headers["X-Prism-Workspace"] = workspaceId;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload, credentials: "same-origin" });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let code = "HttpError";
    let message = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      code = j?.error?.code ?? code;
      message = j?.error?.message ?? message;
    } catch {
      /* not JSON */
    }
    if (res.status === 403 && message.includes("not a member of that workspace")) setWorkspace(null);
    throw new ApiError(res.status, code, message);
  }
  if (opts.raw) return (await res.text()) as T;
  return (await res.json()) as T;
}

export const get = <T,>(p: string) => api<T>("GET", p);
export const post = <T,>(p: string, b?: Body) => api<T>("POST", p, b);
export const put = <T,>(p: string, b?: Body) => api<T>("PUT", p, b);
export const patch = <T,>(p: string, b?: Body) => api<T>("PATCH", p, b);
export const del = <T,>(p: string) => api<T>("DELETE", p);

/** Download an authenticated file (sends the workspace header, saves the blob). */
export async function download(path: string): Promise<void> {
  const headers: Record<string, string> = {};
  if (workspaceId) headers["X-Prism-Workspace"] = workspaceId;
  const res = await fetch(path, { headers, credentials: "same-origin" });
  if (!res.ok) {
    let message = `Download failed (${res.status})`;
    try {
      message = (await res.json())?.error?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, "DownloadFailed", message);
  }
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? "download";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Fetch raw text (e.g. an SVG) with auth headers. */
export async function getText(path: string): Promise<string> {
  return api<string>("GET", path, undefined, { raw: true });
}

// ---------- Types ----------

export type Role = "viewer" | "explorer" | "author" | "steward" | "admin" | "auditor";
export type PrismType = "integer" | "float" | "string" | "date" | "boolean";

export interface User { id: string; email: string; name: string; is_superadmin: boolean; last_login_at?: string | null; created_at?: string; is_active?: boolean }
export interface Workspace { id: string; name: string; slug: string; role?: Role }
export interface Me { user: User; workspace: Workspace; workspaces: Workspace[]; role: Role; via: string }

export interface ColumnContract { name: string; type: PrismType; role: string; locale: string; nullable: boolean; description?: string | null; source_name?: string | null }
export interface ColumnStats { type: string; nulls: number; null_ratio: number; distinct?: number; min?: number | string; max?: number | string; mean?: number; sum?: number; top?: { value: unknown; count: number }[]; true?: number }
export interface Version { id: string; version: number; row_count: number; quarantine_count: number; content_hash: string; source_sha256?: string; created_at: string; columns: ColumnContract[]; profile: { row_count: number; columns: Record<string, ColumnStats> } }
export interface Dataset {
  id: string; name: string; description: string; tags: string[]; status: "draft" | "certified" | "deprecated";
  current_version_id: string | null; created_at: string; updated_at: string;
  row_count?: number; column_count?: number; quarantine_count?: number; version?: number;
  current_version?: Version; versions?: Omit<Version, "profile" | "columns">[];
}

export interface Candidate { type: PrismType; confidence: number; samples: string[]; failures: string[] }
export interface ColumnProposal { index: number; source_name: string; name: string; type: PrismType; locale: string; role: string; nullable: boolean; ambiguous: boolean; null_ratio: number; distinct_ratio: number; candidates: Candidate[]; notes: string[] }
export interface Proposal { header_row: number; data_start_row: number; locale: string; confidence: number; columns: ColumnProposal[]; preview: string[][]; row_estimate: number; warnings: string[]; sheet: string | null; delimiter: string | null; encoding: string | null; needs_review: boolean; sample_truncated?: boolean }
export interface ImportRec { id: string; filename: string; file_kind: "csv" | "xlsx"; size_bytes: number; status: string; sheet_names: { name: string; hidden: boolean }[]; proposal: Proposal; error: string | null; dataset_id: string | null; created_at: string }

export interface Aggregation { column: string; function: "sum" | "avg" | "count" | "min" | "max" | "count_distinct" | "median"; alias?: string | null }
export interface Filter { column: string; operator: string; value: unknown }
export interface QuerySpec { dimensions?: string[]; measures?: Aggregation[]; filters?: Filter[]; sort?: { column: string; direction: "asc" | "desc" }[]; limit?: number | null; columns?: string[]; time_grain?: Record<string, string> }
export interface Encoding { channel: "x" | "y" | "color" | "size"; field: string; label?: string | null }
export interface ViewSpec {
  mark: "bar" | "line" | "area" | "scatter" | "pie" | "kpi" | "table"; encodings: Encoding[]; title?: string | null;
  orientation?: "vertical" | "horizontal"; stacked?: boolean; show_values?: boolean; show_legend?: boolean;
  number_format?: string; currency?: string; time_grain?: string | null; width?: number; height?: number; theme?: string; locale?: string;
}
export interface Chart { id: string; dataset_id: string; name: string; description: string; query: QuerySpec; view: ViewSpec; owner_id: string; updated_at: string; created_at: string }
export interface Tile { chart_id: string; x: number; y: number; w: number; h: number }
export interface Dashboard { id: string; name: string; description: string; layout: Tile[]; updated_at: string; charts?: Record<string, Chart> }
export interface Share { id: string; artifact_type: string; artifact_id: string; created_at: string; expires_at: string | null; revoked_at: string | null; use_count: number; allow_embed: boolean; active: boolean; url?: string; embed_url?: string; token?: string }
export interface QueryResult { columns: string[]; rows: Record<string, unknown>[]; total: number; truncated?: boolean }
export interface AuditEvent { id: string; seq: number; timestamp: string; actor: string | null; action: string; target_type: string | null; target_id: string | null; description: string; details: Record<string, unknown>; ip: string | null }
export interface PlanInfo { code: string; name: string; limits: Record<string, number | null>; features: string[] }
export interface LicenseInfo { status: string; plan: PlanInfo; licensed_plan: string | null; customer: string | null; email: string | null; expires_at: string | null; error: string | null; warnings: string[]; usage: Record<string, number>; plans: Record<string, PlanInfo>; can_manage: boolean; instance_id: string; env_locked: boolean; source: string | null }

export const ROLES: Role[] = ["viewer", "explorer", "author", "steward", "admin", "auditor"];
export const can = {
  author: (r?: Role) => r === "author" || r === "steward" || r === "admin",
  explore: (r?: Role) => r === "explorer" || r === "author" || r === "steward" || r === "admin",
  steward: (r?: Role) => r === "steward" || r === "admin",
  admin: (r?: Role) => r === "admin",
  audit: (r?: Role) => r === "auditor" || r === "admin",
  read: (r?: Role) => r !== "auditor",
};
