import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthContext';
import { Money } from './Money';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const ME = { id: 'k1', username: 'alice', display_name: 'Alice', role: 'child', csrf_token: 'x' };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('kid Money', () => {
  it('shows the balance and transactions newest-first', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/auth/me')) return Promise.resolve(json(ME));
      if (url.includes('/balance')) return Promise.resolve(json({ balance_cents: 450 }));
      if (url.includes('/ledger'))
        return Promise.resolve(
          json([
            { id: 'e1', kind: 'earning', amount_cents: 200, reason: '', created_at: '2025-01-01' },
            { id: 'e2', kind: 'earning', amount_cents: 250, reason: '', created_at: '2025-01-05' },
          ]),
        );
      return Promise.resolve(json([]));
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter>
            <Money />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText('$4.50')).toBeInTheDocument());
    const amounts = screen.getAllByText(/\+\$/).map((n) => n.textContent);
    expect(amounts).toEqual(['+$2.50', '+$2.00']); // newest first
  });

  it('names the chore a penalty was charged for', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/auth/me')) return Promise.resolve(json(ME));
      if (url.includes('/balance')) return Promise.resolve(json({ balance_cents: -200 }));
      if (url.includes('/ledger'))
        return Promise.resolve(
          json([
            {
              id: 'e1',
              kind: 'penalty',
              amount_cents: -200,
              reason: '',
              created_at: '2025-01-01',
              occurrence_id: 'o1',
              chore_id: null,
              chore_title: 'Walk the dog',
              occurrence_due_at: '2025-01-01T18:00:00Z',
            },
          ]),
        );
      return Promise.resolve(json([]));
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter>
            <Money />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/Walk the dog/)).toBeInTheDocument();
    expect(screen.getByText('Missed chore')).toBeInTheDocument();
  });

  it('opens the chore behind an entry, and leaves entries with no chore alone', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/auth/me')) return Promise.resolve(json(ME));
      if (url.includes('/balance')) return Promise.resolve(json({ balance_cents: 300 }));
      if (url.includes('/ledger'))
        return Promise.resolve(
          json([
            {
              id: 'e1',
              kind: 'earning',
              amount_cents: 200,
              reason: '',
              created_at: '2025-01-01',
              occurrence_id: 'o1',
              chore_title: 'Walk the dog',
            },
            {
              id: 'e2',
              kind: 'payout',
              amount_cents: -100,
              reason: '',
              created_at: '2025-01-02',
              occurrence_id: null,
            },
          ]),
        );
      return Promise.resolve(json([]));
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter>
            <Money />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );

    const chore = await screen.findByText(/Walk the dog/);
    expect(chore.closest('a')).toHaveAttribute('href', '/me/chores/o1');
    // A payout has no occurrence behind it — no tap that leads nowhere.
    expect(screen.getByText('Paid out').closest('a')).toBeNull();
  });

  it('does not call a hand-applied penalty a missed chore', async () => {
    // Both are `penalty` kind, so the flat label map used to read "Missed chore" on a
    // charge for something that was never a chore at all (spec §4.8).
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/auth/me')) return Promise.resolve(json(ME));
      if (url.includes('/balance')) return Promise.resolve(json({ balance_cents: -200 }));
      if (url.includes('/ledger'))
        return Promise.resolve(
          json([
            {
              id: 'e1',
              kind: 'penalty',
              amount_cents: -200,
              reason: '',
              created_at: '2025-01-01',
              occurrence_id: null,
              chore_id: 'c4',
            },
          ]),
        );
      return Promise.resolve(json([]));
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter>
            <Money />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Penalty')).toBeInTheDocument();
    expect(screen.queryByText('Missed chore')).not.toBeInTheDocument();
  });
});
