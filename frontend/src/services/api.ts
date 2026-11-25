import { config } from "./config";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(messageFor(status, detail));
  }
}

export function messageFor(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  if (Array.isArray(detail)) return "Please check the form and try again.";
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You don't have permission to do that.";
  if (status === 404) return "Not found.";
  if (status === 413) return "That file is too large.";
  return "Something went wrong. Please try again.";
}

type Body = BodyInit | Record<string, unknown> | undefined;

export async function apiRequest<T>(
  path: string,
  token: string | null,
  init: { method?: string; body?: Body; headers?: Record<string, string> } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (init.body instanceof FormData || typeof init.body === "string") {
    body = init.body;
  } else if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  const resp = await fetch(`${config.apiUrl}${path}`, { method: init.method || "GET", headers, body });
  if (resp.status === 204) return undefined as T;
  const data = resp.headers.get("content-type")?.includes("json") ? await resp.json() : null;
  if (!resp.ok) throw new ApiError(resp.status, data?.detail);
  return data as T;
}
