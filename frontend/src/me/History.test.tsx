import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthContext';
import { History } from './History';

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
    verification_error: null,
  };
}

const ME = { id: 'k1', username: 'alice', display_name: 'Alice', role: 'child', csrf_token: 'x' };

/** A penalty a parent charged by hand: no occurrence, a rule behind it (spec §4.8). */
function penalty(over: Record<string, unknown> = {}) {
  return {
    id: 'pen1',
    kind: 'penalty',
    amount_cents: -150,
    reason: 'House rules: swore at your sister',
    created_at: new Date().toISOString(),
    occurrence_id: null,
    reversed_by_entry_id: null,
    chore_id: 'r1',
    chore_title: 'House rules',
    occurrence_due_at: null,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockApi(occCalls: string[], ledger: unknown[] = []) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('/auth/me')) return Promise.resolve(json(ME));
    if (url.includes('/ledger')) return Promise.resolve(json(ledger));
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
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <History />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('kid History', () => {
  it('shows finished occurrences, excludes to-do ones, and fetches once', async () => {
    const occCalls: string[] = [];
    mockApi(occCalls);

    await waitFor(() => expect(screen.getAllByText('Empty the sink')).toHaveLength(2));

    // `from` is memoised → stable query key → one request. A per-render value
    // churns the key and the spinner never clears.
    expect(new Set(occCalls).size).toBe(1);
    expect(screen.getByText('Done ✅')).toBeInTheDocument();
    expect(screen.getByText('Missed')).toBeInTheDocument();
    expect(screen.queryByText('Do it')).not.toBeInTheDocument();
    expect(screen.getAllByRole('link')[0]).toHaveAttribute('href', '/me/chores/a1');
  });

  it('keeps charged penalties in the record, and drops undone ones', async () => {
    mockApi(
      [],
      [
        penalty(),
        penalty({ id: 'pen2', chore_title: 'Undone rule', reversed_by_entry_id: 'adj1' }),
        // A missed chore's charge is already the occurrence row above it.
        penalty({ id: 'pen3', chore_title: 'Empty the sink', occurrence_id: 'm1', chore_id: null }),
      ],
    );

    expect(await screen.findByText('Penalties')).toBeInTheDocument();
    expect(screen.getByText('House rules')).toBeInTheDocument();
    expect(screen.getByText('House rules: swore at your sister')).toBeInTheDocument();
    expect(screen.getByText('-$1.50')).toBeInTheDocument();
    expect(screen.queryByText('Undone rule')).not.toBeInTheDocument();
    // Two occurrence rows for the chore, and no third row from the ledger.
    expect(screen.getAllByText('Empty the sink')).toHaveLength(2);
  });
});
