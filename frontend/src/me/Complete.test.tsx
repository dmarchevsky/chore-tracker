import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Complete } from './Complete';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

function occ(id: string, status: string, chore_id = 'c1') {
  return {
    id,
    chore_id,
    assignee_id: 'k1',
    window_open_at: '2025-01-01T00:00:00Z',
    due_at: '2025-01-02T00:00:00Z',
    status,
    was_late: false,
    settlement_locked_at: null,
    reward_cents: 200,
    penalty_cents: 0,
    prompt_token: null,
    verification_error: null,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('kid Complete', () => {
  it('shows finished occurrences, excludes to-do ones, and fetches once', async () => {
    const occCalls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/occurrences')) {
        occCalls.push(url);
        return Promise.resolve(
          json([
            occ('a1', 'approved'),
            occ('m1', 'missed'),
            occ('o1', 'open'), // must be filtered out
          ]),
        );
      }
      if (url.includes('/chores'))
        return Promise.resolve(json([{ id: 'c1', title: 'Empty the sink' }]));
      return Promise.resolve(json([]));
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Complete />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getAllByText('Empty the sink')).toHaveLength(2));

    // `from` is memoised → stable query key → one request. A per-render value
    // churns the key and the spinner never clears.
    expect(new Set(occCalls).size).toBe(1);
    expect(screen.getByText('Done ✅')).toBeInTheDocument();
    expect(screen.getByText('Missed')).toBeInTheDocument();
    expect(screen.queryByText('Do it')).not.toBeInTheDocument();
    expect(screen.getAllByRole('link')[0]).toHaveAttribute('href', '/me/chores/a1');
  });
});
