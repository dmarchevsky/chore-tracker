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
});
