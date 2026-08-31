// Thin fetch wrapper for /api/v1. Sends the session cookie automatically and echoes
// the CSRF token on mutations (spec §10).

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let csrfToken = '';
export function setCsrfToken(token: string) {
  csrfToken = token;
}

const BASE = '/api/v1';
const SAFE = new Set(['GET', 'HEAD']);

/** A GET that also needs a response header — used for paged lists (X-Total-Count). */
export async function getPage<T>(path: string): Promise<{ items: T; total: number }> {
  const resp = await fetch(BASE + path, { method: 'GET', credentials: 'same-origin' });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  const items = (await resp.json()) as T;
  return { items, total: Number(resp.headers.get('X-Total-Count') ?? 0) };
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const init: RequestInit = { method, credentials: 'same-origin', headers };
  if (!SAFE.has(method)) headers['X-CSRF-Token'] = csrfToken;

  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  const resp = await fetch(BASE + path, init);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const j = await resp.json();
      detail = j.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  const ct = resp.headers.get('content-type') ?? '';
  return (ct.includes('application/json') ? await resp.json() : await resp.text()) as T;
}

export const api = {
  get: <T>(p: string) => request<T>('GET', p),
  post: <T>(p: string, body?: unknown) => request<T>('POST', p, body),
  patch: <T>(p: string, body?: unknown) => request<T>('PATCH', p, body),
  del: <T>(p: string, body?: unknown) => request<T>('DELETE', p, body),
};
