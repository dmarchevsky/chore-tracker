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

interface FieldError {
  loc?: (string | number)[];
  msg?: string;
}

/** FastAPI sends `detail` as a string for an HTTPException but as an ARRAY of
 *  {type, loc, msg, input} when request-body validation fails. Handing that array to Error()
 *  coerces it to "[object Object]", so flatten it into something a parent can act on. */
function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const shown = (detail as FieldError[]).slice(0, 3).map((e) => {
      // Drop the leading "body" — every field error has it and it tells the reader nothing.
      const where = (e.loc ?? []).filter((p) => p !== 'body').join('.');
      const msg = e.msg ?? 'is not valid';
      return where ? `${where}: ${msg}` : msg;
    });
    const rest = detail.length - shown.length;
    if (rest > 0) shown.push(`…and ${rest} more`);
    return shown.join('; ') || fallback;
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return fallback;
}

/** Build the error for a failed response, reading the server's detail when there is one. */
async function apiError(resp: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = (await resp.json()).detail;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(resp.status, detailText(detail, resp.statusText));
}

/** Cloudflare Access sessions expire (a month, by policy) while the PWA is still open.
 *  The edge answers the next API call with a redirect to Google, which `fetch` cannot
 *  follow usefully — it comes back as the login HTML instead of JSON. A top-level
 *  navigation is the only thing that can complete an Access round-trip, so send the
 *  browser through one rather than showing an unexplainable failure. */
function reloadIfAccessExpired(resp: Response): void {
  const ct = resp.headers.get('content-type') ?? '';
  if (!ct.includes('text/html')) return;
  window.location.reload();
  throw new ApiError(resp.status, 'Session expired — signing in again…');
}

/** A GET that also needs a response header — used for paged lists (X-Total-Count). */
export async function getPage<T>(path: string): Promise<{ items: T; total: number }> {
  const resp = await fetch(BASE + path, { method: 'GET', credentials: 'same-origin' });
  reloadIfAccessExpired(resp);
  if (!resp.ok) throw await apiError(resp);
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
  reloadIfAccessExpired(resp);
  if (!resp.ok) throw await apiError(resp);
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
