const BASE = "/api/v1";

let accessToken: string | null = sessionStorage.getItem("csai_token");

export function setToken(token: string | null) {
  accessToken = token;
  if (token) sessionStorage.setItem("csai_token", token);
  else sessionStorage.removeItem("csai_token");
}

export function getToken() {
  return accessToken;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function refresh(): Promise<boolean> {
  const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "include" });
  if (!res.ok) return false;
  const body = await res.json();
  setToken(body.access_token);
  return true;
}

export async function api<T>(
  path: string,
  opts: { method?: string; body?: unknown; retry?: boolean } = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: opts.method ?? "GET",
    credentials: "include",
    headers: {
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && opts.retry !== false && (await refresh())) {
    return api<T>(path, { ...opts, retry: false });
  }
  if (!res.ok) {
    let code = "error";
    let message = res.statusText;
    try {
      const b = await res.json();
      const d = b.detail ?? b;
      code = d.error ?? code;
      message = d.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function uploadToPresigned(url: string, file: File, contentType: string): Promise<void> {
  const res = await fetch(url, { method: "PUT", headers: { "Content-Type": contentType }, body: file });
  if (!res.ok) throw new Error(`upload failed: ${res.status}`);
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
