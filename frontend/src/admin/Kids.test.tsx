import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Kids } from './Kids';

function json(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const ALICE = {
  id: 'k1',
  username: 'alice',
  display_name: 'Alice',
  email: 'alice@example.com',
  role: 'child',
  is_active: true,
};

function setup() {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method !== 'GET')
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });

    if (method === 'POST' && url.endsWith('/children')) return Promise.resolve(json(ALICE, 201));
    if (method === 'DELETE') return Promise.resolve(json(null, 204));
    if (url.includes('/checkin-token'))
      return Promise.resolve(
        json({
          token: 't',
          webhook_url: 'http://x/api/v1/checkin/t',
          last_used_at: null,
          stale: true,
        }),
      );
    if (url.endsWith('/children')) return Promise.resolve(json([ALICE]));
    return Promise.resolve(json([]));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Kids />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('admin Kids', () => {
  it('lists kids and creates one', async () => {
    const calls = setup();
    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /add kid/i }));
    fireEvent.change(screen.getByPlaceholderText('username'), { target: { value: 'bob' } });
    fireEvent.change(screen.getByPlaceholderText('display name'), { target: { value: 'Bob' } });
    fireEvent.change(screen.getByPlaceholderText('google address'), {
      target: { value: 'bob@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toMatch(/\/children$/);
    expect(post.body).toEqual({
      username: 'bob',
      display_name: 'Bob',
      email: 'bob@example.com',
    });
  });

  it('deactivates a kid', async () => {
    const calls = setup();
    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Alice'));
    fireEvent.click(await screen.findByRole('button', { name: /deactivate/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true));
    expect(calls.find((c) => c.method === 'DELETE')!.url).toContain('/children/k1');
  });
});
