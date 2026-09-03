import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError, api, getPage } from './client';

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
