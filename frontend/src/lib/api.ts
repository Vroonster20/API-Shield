export type ApiRecord = Record<string, unknown>;

export type FuzzResult = ApiRecord & {
  name?: string;
  expected?: unknown;
  actual?: unknown;
  passed?: boolean;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type RequestOptions = Omit<RequestInit, "headers"> & {
  headers?: HeadersInit;
};

export async function request<T>(
  baseUrl: string,
  endpoint: string,
  options: RequestOptions = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${endpoint}`, {
      ...options,
      headers,
      credentials: "include",
    });
  } catch (error) {
    if (error instanceof Error) {
      throw new ApiError(
        0,
        `Could not reach ${baseUrl}. Check the gateway URL and network connection. ${error.message}`,
      );
    }
    throw new ApiError(0, `Could not reach ${baseUrl}. Check the gateway URL and network connection.`);
  }

  const responseText = await response.text();
  let payload: unknown = null;
  if (responseText) {
    try {
      payload = JSON.parse(responseText) as unknown;
    } catch {
      payload = responseText;
    }
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    if (payload && typeof payload === "object" && "detail" in payload) {
      const message = (payload as { detail: unknown }).detail;
      detail = typeof message === "string" ? message : JSON.stringify(message);
    } else if (typeof payload === "string" && payload.trim()) {
      detail = payload;
    }
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

export async function login(
  baseUrl: string,
  username: string,
  password: string,
): Promise<{ token: string | null }> {
  const payload = await request<unknown>(
    baseUrl,
    "/admin/login",
    { method: "POST", body: JSON.stringify({ username, password }) },
  );

  let token: string | null = null;
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const candidate =
      record.token ?? record.session_token ?? record.access_token;
    if (typeof candidate === "string") token = candidate;
  }
  return { token };
}

export async function getRows(
  baseUrl: string,
  endpoint: string,
  token?: string | null,
  wrappers: string[] = [],
  options: RequestOptions = { method: "GET" },
): Promise<ApiRecord[]> {
  const payload = await request<unknown>(baseUrl, endpoint, options, token);
  let rows: unknown = payload;

  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const record = payload as Record<string, unknown>;
    const wrapper = wrappers.find((key) => key in record);
    if (wrapper) rows = record[wrapper];
  }

  if (!Array.isArray(rows)) {
    throw new ApiError(
      200,
      `The response from ${endpoint} was not a list of records.`,
    );
  }
  if (
    rows.some(
      (row) => !row || typeof row !== "object" || Array.isArray(row),
    )
  ) {
    throw new ApiError(
      200,
      `The response from ${endpoint} contains an invalid record.`,
    );
  }
  return rows as ApiRecord[];
}
