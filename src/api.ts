export interface RateLimit {
  limit: number;
  window_seconds: number;
}
export interface AbuseConfig {
  auto_ban_enabled: boolean;
  strike_limit: number;
  window_seconds: number;
  ban_seconds: number;
}
export interface RouteConfig {
  id: string;
  name: string;
  path: string;
  methods: string[];
  max_body_bytes: number;
  content_types: string[];
  ip_rate: RateLimit | null;
  json_schema: Record<string, unknown> | null;
}
export interface Config {
  schema_version: 1;
  service: {
    id: string;
    name: string;
    public_host: string;
    upstream_id: string;
    enabled: boolean;
    unmatched_action: "baseline" | "deny";
    max_body_bytes: number;
    ip_rate: RateLimit;
    abuse: AbuseConfig;
    routes: RouteConfig[];
  };
}
export interface Session {
  admin: { id: string; username: string };
  csrf_token: string;
  expires_at_ms: number;
}
export interface ConfigResponse {
  version: number | null;
  document: Config | null;
}
export interface ApplyResponse {
  desired_version: number;
  applied_version: number | null;
  status: "pending";
}
export interface Status {
  desired_version: number | null;
  applied_version: number | null;
  heartbeat_ms: number | null;
  apply_error_code: string | null;
  apply_error_version: number | null;
  status: string;
  gateway_instance_id: string | null;
  started_at_ms: number | null;
  dropped_events_since_start: number | null;
}
export interface Ban {
  ban_id: string;
  client_digest: string;
  source: string;
  created_at_ms: number;
  expires_at_ms: number;
  revoked_at_ms: number | null;
  status: "active" | "expired" | "revoked";
  reason_code: string;
}
export interface RequestEvent {
  id: number;
  at_ms: number;
  request_id: string | null;
  config_version: number | null;
  route_id: string | null;
  method: string;
  decision: string;
  reason_code: string | null;
  status_code: number | null;
  upstream_status: number | null;
  client_digest: string | null;
  duration_ms: number;
  origin_attempted: boolean;
  truncated: boolean;
}
export interface SecurityEvent {
  id: number;
  at_ms: number;
  event_type: string;
  actor_type: string;
  service_id: string | null;
  client_digest: string | null;
  entity_id: string | null;
  request_id: string | null;
  safe_details: Record<string, unknown> | null;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  earliest_retained_ms?: number | null;
  telemetry_complete?: false;
}
export interface FuzzSummary {
  run_id: string;
  profile_id: string;
  seed: number;
  state: string;
  created_at_ms: number;
  started_at_ms: number | null;
  finished_at_ms: number | null;
  passed_count: number;
  failed_count: number;
  error_count: number;
}
export interface FuzzCase {
  case_id: string;
  expected: string;
  actual: string;
  outcome: "passed" | "failed" | "error";
  request_id: string | null;
  elapsed_ms: number;
  origin_receipt_delta: number;
}
export interface FuzzDetail extends FuzzSummary {
  cases: FuzzCase[];
}

let csrfToken = "";
export function setSession(session: Session | null): void {
  csrfToken = session?.csrf_token ?? "";
}
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD" && csrfToken)
    headers.set("X-CSRF-Token", csrfToken);
  let response: Response;
  try {
    response = await fetch(`/admin/v1${path}`, {
      ...init,
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    throw new ApiError(
      0,
      "NETWORK_ERROR",
      "Could not reach the management server. Check the connection and try again.",
    );
  }
  if (!response.ok) {
    let code = "REQUEST_FAILED";
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "error" in body) {
        const error = body.error;
        if (
          error &&
          typeof error === "object" &&
          "code" in error &&
          typeof error.code === "string"
        )
          code = error.code;
      }
    } catch {
      /* generic error only */
    }
    const descriptions: Record<string, string> = {
      ADMIN_UNAUTHENTICATED: "Your session expired. Sign in again.",
      CSRF_REJECTED: "Security check failed. Refresh the page and try again.",
      CONFIG_CONFLICT:
        "Settings changed elsewhere. Your edits are preserved; reload the server version before saving.",
      CONFIG_INVALID:
        "Settings were rejected. Check the fields and schema, then try again.",
      BAN_ALREADY_ACTIVE: "This identity already has an active ban.",
      BAN_REPLACED:
        "This ban has been replaced by a newer ban. Refresh the list.",
      FUZZ_BUSY: "A fuzz run is already queued or running.",
      ADMIN_BUSY: "The admin server is busy. Try again shortly.",
      STORAGE_UNAVAILABLE:
        "The protection store is unavailable. Try again shortly.",
    };
    throw new ApiError(
      response.status,
      code,
      descriptions[code] ?? `Request failed (${response.status}, ${code}).`,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export const post = <T>(path: string, body: unknown): Promise<T> =>
  api(path, { method: "POST", body: JSON.stringify(body) });
