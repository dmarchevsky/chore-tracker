import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Pending } from './Pending';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

function occ(over: Record<string, unknown>) {
  return {
    id: 'x',
    chore_id: 'c1',
    assignee_id: 'k1',
    window_open_at: new Date().toISOString(),
    due_at: new Date().toISOString(),
    status: 'open',
    was_late: false,
    settlement_locked_at: null,
    reward_cents: 200,
    penalty_cents: 0,
    prompt_token: null,
    verification_error: null,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderPending() {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('status=open'))
      return Promise.resolve(json([occ({ id: 'o1', status: 'open' })]));
    if (url.includes('status=verified_fail')) return Promise.resolve(json([]));
    if (url.includes('status=pending'))
      return Promise.resolve(
        json([occ({ id: 'p1', status: 'pending', chore_id: 'c2', window_open_at: soon() })]),
      );
    if (url.includes('/chores'))
      return Promise.resolve(
        json([
          { id: 'c1', title: 'Empty the sink' },
          { id: 'c2', title: 'Walk the dog' },
        ]),
      );
    return Promise.resolve(json([]));
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Pending />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function soon() {
  return new Date(Date.now() + 6 * 3600_000).toISOString();
}

describe('kid Pending', () => {
  it('lists open chores as tappable rows and pending ones under Later, not tappable', async () => {
    renderPending();

    const doNow = await screen.findByText('Empty the sink');
    expect(doNow.closest('a')).toHaveAttribute('href', '/me/chores/o1');
    expect(screen.getByText('Do it')).toBeInTheDocument();

    expect(screen.getByText('Coming up')).toBeInTheDocument();
    const later = screen.getByText('Walk the dog');
    expect(later.closest('a')).toBeNull();
  });
});
