import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ChoreList } from './ChoreList';

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ChoreList scope="today" title="Today" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ChoreList (kid Today)', () => {
  it('shows actionable chores with the reward and no confidence numbers', async () => {
    const soon = new Date(Date.now() + 30 * 60_000).toISOString();
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/occurrences'))
        return Promise.resolve(
          jsonResponse([
            {
              id: 'o1',
              chore_id: 'c1',
              assignee_id: 'k1',
              window_open_at: soon,
              due_at: soon,
              status: 'open',
              was_late: false,
              settlement_locked_at: null,
              reward_cents: 250,
              penalty_cents: 0,
              prompt_token: null,
              verification_error: null,
            },
          ]),
        );
      if (url.includes('/chores'))
        return Promise.resolve(jsonResponse([{ id: 'c1', title: 'Empty the sink' }]));
      return Promise.resolve(jsonResponse([]));
    });

    renderList();
    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    expect(screen.getByText(/\$2\.50/)).toBeInTheDocument();
    expect(screen.getByText('Do it')).toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });
});
