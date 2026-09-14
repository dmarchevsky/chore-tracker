import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError, api, getPage, setCsrfToken, setCurrentUserId } from './client';

function res(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'X-Total-Count': '7' },
  });
}

const stub = (r: Response) => vi.spyOn(globalThis, 'fetch').mockResolvedValue(r);

afterEach(() => vi.restoreAllMocks());

describe('api error detail', () => {
  it('renders a FastAPI validation array as readable text, not [object Object]', async () => {
    stub(
      res(422, {
        detail: [
          {
            type: 'string_too_short',
            loc: ['body', 'outcome_tiers', 0, 'condition'],
            msg: 'String should have at least 1 character',
          },
        ],
      }),
    );

    await expect(api.patch('/chores/c1', {})).rejects.toThrow(
      'outcome_tiers.0.condition: String should have at least 1 character',
    );
    await expect(api.patch('/chores/c1', {})).rejects.not.toThrow('[object Object]');
  });

  it('keeps a plain string detail verbatim', async () => {
    stub(res(409, { detail: 'occurrence is settlement-locked and cannot be changed' }));

    await expect(api.post('/occurrences/o1/decision', {})).rejects.toThrow(
      'occurrence is settlement-locked and cannot be changed',
    );
  });

  it('summarises a long list instead of dumping every field', async () => {
    const detail = Array.from({ length: 5 }, (_, i) => ({
      loc: ['body', `f${i}`],
      msg: 'nope',
    }));
    stub(res(422, { detail }));

    await expect(api.post('/chores', {})).rejects.toThrow('…and 2 more');
  });

  it('carries the status code', async () => {
    stub(res(404, { detail: 'chore not found' }));

    await expect(api.get('/chores/nope')).rejects.toMatchObject({
      status: 404,
      message: 'chore not found',
    } satisfies Partial<ApiError>);
  });

  it('falls back to the status text when the body is not JSON', async () => {
    stub(new Response('<html>502</html>', { status: 502, statusText: 'Bad Gateway' }));

    await expect(api.get('/health')).rejects.toThrow('Bad Gateway');
  });

  it('getPage surfaces the server detail instead of the bare status text', async () => {
    stub(res(422, { detail: [{ loc: ['query', 'limit'], msg: 'Input should be less than 200' }] }));

    await expect(getPage('/occurrences?limit=999')).rejects.toThrow(
      'limit: Input should be less than 200',
    );
  });

  it('still reads the total header on success', async () => {
    stub(res(200, [{ id: 'o1' }]));

    await expect(getPage('/occurrences')).resolves.toEqual({ items: [{ id: 'o1' }], total: 7 });
  });
});

/** What the edge answers with when it, rather than our API, handles the request: the
 *  Cloudflare Access login page, or a Cloudflare error page while the origin is down. */
function html(status: number) {
  return new Response('<!doctype html><title>Just a moment…</title>', {
    status,
    headers: { 'content-type': 'text/html; charset=UTF-8' },
  });
}

describe('an HTML answer from the edge', () => {
  const reload = vi.fn();

  beforeEach(() => {
    reload.mockClear();
    sessionStorage.clear();
    vi.stubGlobal('location', { reload });
  });

  afterEach(() => vi.unstubAllGlobals());

  it('navigates once, because only a navigation can finish an Access sign-in', async () => {
    stub(html(200));

    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(NetworkError);
    expect(reload).toHaveBeenCalledOnce();
  });

  it('does not navigate again, however long the HTML keeps coming', async () => {
    // The regression test for a refresh loop with no exit: the trigger is the content type
    // alone, and a Cloudflare error page while the origin is down is HTML that will not
    // stop arriving. Reloading on each one spins the tab forever.
    stub(html(530));

    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(NetworkError);
    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(NetworkError);
    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(NetworkError);

    expect(reload).toHaveBeenCalledOnce();
  });

  it('gets its one reload back once the API answers properly again', async () => {
    // The guard is for a loop, not a lifetime ban: an Access session that expires later in
    // the same tab still deserves the navigation that signs the visitor back in.
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(html(200))
      .mockResolvedValueOnce(res(200, { id: 'u1' }))
      .mockResolvedValueOnce(html(200));

    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(NetworkError);
    expect(reload).toHaveBeenCalledOnce();

    await api.get('/auth/me');

    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(NetworkError);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it('still reloads exactly once when the mark cannot be stored', async () => {
    // A private window, or a browser set to block site data. Losing the guard is bad; a
    // throw from inside the fetch path would be worse.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    stub(html(200));

    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(NetworkError);
    expect(reload).toHaveBeenCalledOnce();
  });

  it('applies to paged lists too', async () => {
    stub(html(200));
    await expect(getPage('/occurrences')).rejects.toBeInstanceOf(NetworkError);
    expect(reload).toHaveBeenCalledOnce();
  });
});

describe('silent session recovery', () => {
  // The app's own session is 12 hours for a parent; the Cloudflare Access session is a
  // month. So the ordinary case is an expired cookie behind a perfectly good Access
  // assertion, which /auth/me can turn back into a session with nobody being asked
  // anything. Before this, the parent met a dead screen every morning.
  const ME = { id: 'u1', role: 'admin', csrf_token: 'fresh' };

  function router(handlers: { probe: () => Response; api: () => Response }) {
    const seen: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      seen.push(url);
      return Promise.resolve(url.includes('/auth/me') ? handlers.probe() : handlers.api());
    });
    return seen;
  }

  beforeEach(() => setCurrentUserId('u1'));

  it('re-establishes the session on a 401 and replays the call', async () => {
    let n = 0;
    const seen = router({
      probe: () => res(200, ME),
      api: () => (++n === 1 ? res(401, { detail: 'expired' }) : res(200, [{ id: 'o1' }])),
    });

    await expect(api.get('/occurrences')).resolves.toEqual([{ id: 'o1' }]);
    expect(seen.filter((u) => u.includes('/auth/me'))).toHaveLength(1);
  });

  it('probes once for a screenful of simultaneous 401s', async () => {
    // Every query on the screen refires together when the app is resumed. One probe per
    // caller would mint a session row each, and all but the last replay would carry a CSRF
    // token that no longer matches the cookie.
    let n = 0;
    const seen = router({
      probe: () => res(200, ME),
      api: () => (++n <= 4 ? res(401, { detail: 'expired' }) : res(200, [])),
    });

    await Promise.all([
      api.get('/occurrences'),
      api.get('/chores'),
      api.get('/children'),
      api.get('/disputes'),
    ]);
    expect(seen.filter((u) => u.includes('/auth/me'))).toHaveLength(1);
  });

  it('replays a mutation with the csrf token the new session minted', async () => {
    const sent: (string | null)[] = [];
    let n = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes('/auth/me')) return Promise.resolve(res(200, ME));
      sent.push(new Headers(init?.headers).get('X-CSRF-Token'));
      return Promise.resolve(++n === 1 ? res(401, { detail: 'expired' }) : res(200, {}));
    });

    setCsrfToken('stale');
    await api.post('/occurrences/o1/decision', { action: 'approve' });
    expect(sent).toEqual(['stale', 'fresh']);
  });

  it('never probes from inside the probe', async () => {
    const seen = router({ probe: () => res(401, { detail: 'no' }), api: () => res(401, {}) });

    await expect(api.get('/auth/me')).rejects.toBeInstanceOf(ApiError);
    expect(seen).toHaveLength(1);
  });

  it('surfaces the original error when there is no session to recover', async () => {
    // The dev stack has no Access assertion, so /auth/me legitimately 401s. The app must
    // fall through to Login rather than loop.
    let n = 0;
    router({
      probe: () => res(401, { detail: 'not authenticated' }),
      api: () => (++n === 1 ? res(401, { detail: 'expired' }) : res(200, [])),
    });

    await expect(api.get('/occurrences')).rejects.toMatchObject({ status: 401 });
  });

  it('reloads instead of replaying when somebody else is now signed in', async () => {
    // Shared family tablet: replaying would paint one kid's data into the other's shell.
    const reload = vi.fn();
    vi.spyOn(window, 'location', 'get').mockReturnValue({
      ...window.location,
      reload,
    } as unknown as Location);

    let n = 0;
    router({
      probe: () => res(200, { ...ME, id: 'u2' }),
      api: () => (++n === 1 ? res(401, { detail: 'expired' }) : res(200, [])),
    });

    await expect(api.get('/occurrences')).rejects.toMatchObject({ status: 401 });
    expect(reload).toHaveBeenCalled();
  });

  it('recovers a paged list too', async () => {
    let n = 0;
    router({
      probe: () => res(200, ME),
      api: () => (++n === 1 ? res(401, { detail: 'expired' }) : res(200, [{ id: 'h1' }])),
    });

    const page = await getPage<{ id: string }[]>('/occurrences?limit=50');
    expect(page.items).toEqual([{ id: 'h1' }]);
    expect(page.total).toBe(7);
  });
});
