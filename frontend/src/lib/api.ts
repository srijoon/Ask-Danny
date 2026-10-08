// Small typed client for the Flask JSON API. The Next dev proxy forwards /api/*
// to Flask (see next.config.ts), so calls stay same-origin and the session
// cookie just works. CSRF: every mutation sends X-CSRF-Token, and the token
// rotates on login, so the login response replaces it via setCsrfToken().

export interface Pool {
  id: string;
  type: "shared" | "group";
  name: string;
}

export interface User {
  id: string;
  username: string;
  groups: string[];
  isAdmin: boolean;
  pools: Pool[];
}

export interface FileDoc {
  id: string;
  title: string;
  filename: string;
  fileType: string;
  size: number;
  poolIds: string[];
  uploadedBy: string;
  createdAt: string;
  chunkCount: number;
}

export interface Source {
  n: number;
  doc_id: string;
  title: string;
  filename: string | null;
  page: number | null;
  score: number;
  text: string;
}

export interface AnswerPayload {
  content: string;
  status: string; // "ok" | "no_results" | "rate_limited" | "error"
  sources: Source[];
  searchQuery: string;
}

export interface AskResponse {
  conversationId: string;
  title: string;
  answer: AnswerPayload;
}

export interface Usage {
  documents: { count: number; chunks: number; totalBytes: number };
  questions: {
    total: number;
    byStatus: Record<string, number>;
    byUser: Record<string, number>;
  };
  savings: { answerCallsSkipped: number };
  llm: string;
}

export interface AdminUser {
  id: string;
  username: string;
  groups: string[];
  isAdmin: boolean;
  createdAt: string;
}

export interface AdminGroup {
  id: string;
  name: string;
  members: string[];
  documentCount: number;
}

// carries the response body too — upload 409s include fileId, for example
export class ApiError extends Error {
  status: number;
  data: Record<string, unknown>;

  constructor(message: string, status: number, data: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  // called by the login page: the server rotates the token on login, so the
  // pre-login one held here is dead the moment sign-in succeeds
  csrfToken = token;
}

async function csrf(): Promise<string> {
  // lazily fetch-and-cache the token; Flask mints one per session and the
  // before_request hook compares it on every mutation
  if (!csrfToken) {
    const res = await fetch("/api/csrf");
    csrfToken = ((await res.json()) as { csrfToken: string }).csrfToken;
  }
  return csrfToken;
}

// the single funnel every page calls through — it handles CSRF, JSON vs
// multipart bodies, session-expiry redirects, and error unwrapping so callers
// just see typed data or an ApiError
export async function apiFetch<T>(
  path: string,
  options: { method?: string; json?: unknown; form?: FormData } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;

  if (method !== "GET") headers["X-CSRF-Token"] = await csrf();
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  } else if (options.form) {
    // FormData sets its own multipart boundary — don't touch Content-Type
    body = options.form;
  }

  const res = await fetch(path, { method, headers, body, credentials: "same-origin" });

  // a 401 means the session expired — bounce to login (except on /login itself,
  // where 401 just means wrong credentials). a hard navigation also clears any
  // stale client state, which is what we want on session expiry
  if (res.status === 401 && !window.location.pathname.startsWith("/login")) {
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- intentional full reload on session expiry
    window.location.assign("/login");
    throw new ApiError("Session expired", 401, {});
  }

  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    // the API always sends {"error": "..."}; fall back to the HTTP status when
    // a response somehow isn't that shape (proxy down, HTML error page, etc.)
    const message =
      (data as { error?: string } | null)?.error ?? `Request failed (HTTP ${res.status})`;
    throw new ApiError(message, res.status, (data as Record<string, unknown>) ?? {});
  }
  return data as T;
}
