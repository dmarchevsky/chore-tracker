import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Inbox } from './Inbox';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('admin Inbox', () => {
  it('lists items waiting for review and opens the detail pane', async () => {
    const due = new Date().toISOString();
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('inbox=true'))
        return Promise.resolve(
          json([
            {
              id: 'o1',
              chore_id: 'c1',
              assignee_id: 'k1',
              window_open_at: due,
              due_at: due,
              status: 'submitted',
              was_late: false,
              settlement_locked_at: null,
              reward_cents: 200,
              penalty_cents: 0,
              prompt_token: null,
              verification_error: null,
            },
          ]),
        );
      if (url.includes('/chores'))
        return Promise.resolve(json([{ id: 'c1', title: 'Empty the sink' }]));
      if (url.endsWith('/occurrences/o1'))
        return Promise.resolve(
          json({
            id: 'o1',
            chore_id: 'c1',
            status: 'submitted',
            reward_cents: 200,
            due_at: due,
            window_open_at: due,
            prompt_token: null,
            settlement_locked_at: null,
            assignee_id: 'k1',
            was_late: false,
            penalty_cents: 0,
            verification_error: null,
          }),
        );
      return Promise.resolve(json([]));
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Inbox />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText('Empty the sink')).toBeInTheDocument());
    screen.getByText('Empty the sink').click();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText(/reason/i)).toBeInTheDocument();
  });
});
