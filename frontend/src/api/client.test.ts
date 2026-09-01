import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, getPage } from './client';

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
