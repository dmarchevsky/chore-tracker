// Thin fetch wrapper for /api/v1. Sends the session cookie automatically and echoes
// the CSRF token on mutations (spec §10).

import type { Me } from './types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** The request never produced an HTTP status: offline, or the edge answered with a
 *  cross-origin redirect that `fetch` refuses to follow. Distinguished from ApiError
 *  because "no answer" and "answered 401" call for very different things to be said. */
export class NetworkError extends Error {}

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(BASE + path, init);
  } catch {
    throw new NetworkError('could not reach ChoreKeeper');
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

// Per tab, and gone when the tab closes — which is the right granularity for "we have
// already tried reloading once in this sitting".
const RELOADED = 'chorekeeper.access-reload';

function reloadedAlready(): boolean {
  try {
    return sessionStorage.getItem(RELOADED) === '1';
  } catch {
    // Site data blocked. Degrade to reloading every time rather than throwing inside the
    // fetch path — no worse than the behaviour this guard replaced.
    return false;
  }
}

function markReloaded(on: boolean): void {
  try {
    if (on) sessionStorage.setItem(RELOADED, '1');
    else sessionStorage.removeItem(RELOADED);
  } catch {
    /* see above */
  }
}

/** Cloudflare Access sessions expire (a month, by policy) while the PWA is still open.
 *  The edge answers the next API call with a redirect to Google, which `fetch` cannot
 *  follow usefully — it comes back as the login HTML instead of JSON. A top-level
 *  navigation is the only thing that can complete an Access round-trip, so send the
 *  browser through one rather than showing an unexplainable failure.
 *
 *  Once, though. The trigger is the content type alone, and plenty of HTML is not a login
 *  page — Cloudflare's own error pages are HTML too, and they keep coming for as long as
 *  the origin is down. Reloading on every one of them is a refresh loop with no exit, so
 *  the second time this happens the app stops and says it cannot reach the server, which
 *  is a screen the visitor can act on. A clean answer clears the mark, so a genuine
 *  expiry later in the same tab still gets its one reload. */
function reloadIfAccessExpired(resp: Response): void {
  const ct = resp.headers.get('content-type') ?? '';
  if (!ct.includes('text/html')) {
    if (reloadedAlready()) markReloaded(false);
    return;
  }
  if (!reloadedAlready()) {
    markReloaded(true);
    window.location.reload();
  }
  // NetworkError, not ApiError: whatever answered, it was not our API, and this is exactly
  // the state the Login screen calls "could not reach ChoreKeeper" — where Try again is a
  // real navigation and the reset button is one line below it.
  throw new NetworkError('could not reach ChoreKeeper');
}

/** Who the session belongs to, so recovery can tell a refresh from a change of person.
 *  Set by AuthContext on every successful probe. */
let currentUserId: string | null = null;
export function setCurrentUserId(id: string | null) {
  currentUserId = id;
}

/** Paths that must never trigger a recovery attempt: probing from inside the probe, or
 *  from a sign-in that is itself establishing the session, recurses forever. */
const NO_RECOVERY = ['/auth/me', '/auth/login', '/auth/dev/login', '/auth/logout'];

/** One shared attempt. On resume every query on the screen fires at once and they all get
 *  401 together; letting each one probe would mint a session row per caller, each setting
 *  its own cookie. Last write would win and every other replay would carry a CSRF token
 *  that no longer matches the cookie — so the recovery would itself cause 403s. */
let recovering: Promise<Me | null> | null = null;

/** Re-establish the app session without involving the visitor.
 *
 * The app's own session is much shorter than the Cloudflare Access one (12 hours for a
 * parent, against a month at the edge), so the ordinary case is an expired cookie behind a
 * perfectly good Access assertion. `/auth/me` mints a fresh session straight from that
 * assertion, which makes this recoverable in the background — the alternative was the
 * parent meeting a dead screen every morning with nothing to do but reload.
 *
 * Distinct from `reloadIfAccessExpired` above, which handles the *edge* session ending: that
 * answers with HTML and can only be fixed by a top-level navigation. This one is our own
 * session ending, which answers 401 JSON and can be fixed silently.
 */
async function recoverSession(): Promise<Me | null> {
  recovering ??= (async () => {
    try {
      const resp = await send('/auth/me', { method: 'GET', credentials: 'same-origin' });
      if (!resp.ok) return null;
      const me = (await resp.json()) as Me;
      // The new session carries a NEW csrf token; replaying a mutation with the old one is
      // a guaranteed 403, so adopt it before anything is retried.
      setCsrfToken(me.csrf_token ?? '');
      return me;
    } catch {
      return null; // offline, or the edge answered — nothing to recover to
    } finally {
      // Cleared on the next tick so everyone who joined this attempt reads its result,
      // and a later expiry still gets an attempt of its own.
      queueMicrotask(() => {
        recovering = null;
      });
    }
  })();
  return recovering;
}

/** Should this 401 be retried, and is the session we recovered still the same person? */
async function canReplay(path: string, resp: Response): Promise<boolean> {
  if (resp.status !== 401) return false;
  if (NO_RECOVERY.some((p) => path.startsWith(p))) return false;

  const before = currentUserId;
  const me = await recoverSession();
  if (me === null) return false;

  // A different person is signed in at the edge now — a shared tablet where someone else
  // picked their Google account. Replaying would paint their data into a shell built for
  // whoever was here before, so start the document again instead.
  if (before !== null && me.id !== before) {
    window.location.reload();
    return false;
  }
  currentUserId = me.id;
  return true;
}

/** A GET that also needs a response header — used for paged lists (X-Total-Count). */
export async function getPage<T>(path: string): Promise<{ items: T; total: number }> {
  let resp = await send(path, { method: 'GET', credentials: 'same-origin' });
  reloadIfAccessExpired(resp);
  if (await canReplay(path, resp)) {
    resp = await send(path, { method: 'GET', credentials: 'same-origin' });
    reloadIfAccessExpired(resp);
  }
  if (!resp.ok) throw await apiError(resp);
  const items = (await resp.json()) as T;
  return { items, total: Number(resp.headers.get('X-Total-Count') ?? 0) };
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Rebuilt per attempt: a replay has to pick up the csrf token the recovered session
  // minted, and reuse the same body.
  const build = (): RequestInit => {
    const headers: Record<string, string> = {};
    const init: RequestInit = { method, credentials: 'same-origin', headers };
    if (!SAFE.has(method)) headers['X-CSRF-Token'] = csrfToken;
    if (body instanceof FormData) {
      init.body = body;
    } else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return init;
  };

  let resp = await send(path, build());
  reloadIfAccessExpired(resp);
  if (await canReplay(path, resp)) {
    resp = await send(path, build());
    reloadIfAccessExpired(resp);
  }
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
