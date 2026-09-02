import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthContext';
import { Today } from './Today';

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
    verification_error: null,
    ...over,
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

function renderToday(ledger: unknown[] = []) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('status=open'))
      return Promise.resolve(json([occ({ id: 'o1', status: 'open' })]));
    if (url.includes('status=verified_fail')) return Promise.resolve(json([]));
    if (url.includes('status=missed'))
      return Promise.resolve(
        json([occ({ id: 'm1', status: 'missed', chore_id: 'c4', penalty_cents: 100 })]),
      );
    if (url.includes('status=pending'))
      return Promise.resolve(
        json([
          // The same chore materialised across the horizon, out of order.
          occ({ id: 'p2', status: 'pending', chore_id: 'c2', window_open_at: soon(48) }),
          occ({ id: 'p1', status: 'pending', chore_id: 'c2', window_open_at: soon() }),
          occ({ id: 'p3', status: 'pending', chore_id: 'c2', window_open_at: soon(24) }),
          occ({ id: 'p4', status: 'pending', chore_id: 'c3', window_open_at: soon(12) }),
        ]),
      );
    if (url.includes('/auth/me')) return Promise.resolve(json(ME));
    if (url.includes('/ledger')) return Promise.resolve(json(ledger));
    if (url.includes('/chores'))
      return Promise.resolve(
        json([
          { id: 'c1', title: 'Empty the sink' },
          { id: 'c2', title: 'Walk the dog' },
          { id: 'c3', title: 'Take out the bins' },
          { id: 'c4', title: 'Feed the cat' },
        ]),
      );
    return Promise.resolve(json([]));
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <Today />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function soon(hours = 6) {
  return new Date(Date.now() + hours * 3600_000).toISOString();
}

describe('kid Today', () => {
  it('lists open chores as tappable rows and pending ones under Later, not tappable', async () => {
    renderToday();

    const doNow = await screen.findByText('Empty the sink');
    expect(doNow.closest('a')).toHaveAttribute('href', '/me/chores/o1');
    expect(screen.getByText('Do it')).toBeInTheDocument();

    expect(screen.getByText('Coming up')).toBeInTheDocument();
    const later = screen.getByText('Walk the dog');
    expect(later.closest('a')).toBeNull();
  });

  it('lists chores missed today, tappable so the kid can still dispute them', async () => {
    renderToday();

    expect(await screen.findByText('Missed today')).toBeInTheDocument();
    const miss = screen.getByText('Feed the cat');
    expect(miss.closest('a')).toHaveAttribute('href', '/me/chores/m1');
  });

  it('shows only the next upcoming occurrence of each chore', async () => {
    renderToday();
    await screen.findByText('Coming up');

    // Three pending "Walk the dog" rows collapse to the soonest one...
    expect(screen.getAllByText('Walk the dog')).toHaveLength(1);
    // Four pending occurrences in, two rows out — one per chore.
    expect(screen.getAllByText(/opens/)).toHaveLength(2);
    // ...and a different chore still gets its own row.
    expect(screen.getByText('Take out the bins')).toBeInTheDocument();
  });

  it('shows penalties charged today, and leaves undone ones off', async () => {
    renderToday([
      penalty(),
      // Already reversed — no longer charged, so it has no business on today's screen.
      penalty({ id: 'pen2', chore_title: 'Undone rule', reversed_by_entry_id: 'adj1' }),
      // Yesterday's charge belongs to History, not Today.
      penalty({
        id: 'pen3',
        chore_title: 'Old rule',
        created_at: new Date(Date.now() - 36 * 3600_000).toISOString(),
      }),
      // A missed chore's penalty already has an occurrence row of its own.
      penalty({ id: 'pen4', chore_title: 'Feed the cat', occurrence_id: 'm1', chore_id: null }),
    ]);

    expect(await screen.findByText('Penalties')).toBeInTheDocument();
    expect(screen.getByText('House rules')).toBeInTheDocument();
    expect(screen.getByText('House rules: swore at your sister')).toBeInTheDocument();
    expect(screen.getByText('-$1.50')).toBeInTheDocument();
    expect(screen.queryByText('Undone rule')).not.toBeInTheDocument();
    expect(screen.queryByText('Old rule')).not.toBeInTheDocument();
    // "Feed the cat" is on screen once — as the missed-chore row, not twice.
    expect(screen.getAllByText('Feed the cat')).toHaveLength(1);
  });
});
