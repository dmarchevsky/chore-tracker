import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Money } from './Money';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const ALICE = {
  id: 'k1',
  username: 'alice',
  display_name: 'Alice',
  role: 'child',
  is_active: true,
  totp_enrolled: false,
};

const PENALTY = {
  id: 'l1',
  kind: 'penalty',
  amount_cents: -500,
  reason: 'chore missed',
  created_at: '2025-06-02T09:00:00Z',
  occurrence_id: 'o1',
  reversed_by_entry_id: null,
  chore_title: 'Walk the dog',
  occurrence_due_at: '2025-06-01T15:00:00Z',
};

function setup(ledger: unknown[] = [PENALTY]) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method !== 'GET')
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });

    if (method === 'POST') return Promise.resolve(json({}, 200));
    if (url.includes('/ledger')) return Promise.resolve(json(ledger));
    if (url.includes('/balance'))
      return Promise.resolve(json({ child_id: 'k1', balance_cents: -500, currency: 'USD' }));
    if (url.includes('/checkin-token'))
      return Promise.resolve(
        json({ token: 't', webhook_url: 'http://x/t', last_used_at: null, stale: false }),
      );
    if (url.endsWith('/children')) return Promise.resolve(json([ALICE]));
    return Promise.resolve(json([]));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Money />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('admin Money statement', () => {
  it('names the chore behind a penalty instead of just "chore missed"', async () => {
    setup();

    expect(await screen.findByText(/Walk the dog/)).toBeInTheDocument();
    expect(screen.getByText(/chore missed/)).toBeInTheDocument();
  });

  it('excuses a missed chore from the statement, with a reason', async () => {
    const calls = setup();

    fireEvent.click(await screen.findByText('Excuse this'));
    fireEvent.change(screen.getByPlaceholderText(/Why\?/), {
      target: { value: 'we were away' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Excuse' }));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toContain('/occurrences/o1/decision');
    expect(calls[0].body).toEqual({ action: 'excuse', reason: 'we were away' });
  });

  it('will not re-excuse an entry that is already reversed', async () => {
    setup([{ ...PENALTY, reversed_by_entry_id: 'l2' }]);

    expect(await screen.findByText('(reversed)')).toBeInTheDocument();
    expect(screen.queryByText('Excuse this')).not.toBeInTheDocument();
  });

  it('offers nothing to excuse on a payout', async () => {
    setup([
      {
        ...PENALTY,
        id: 'l3',
        kind: 'payout',
        amount_cents: -1000,
        reason: 'cash',
        occurrence_id: null,
        chore_title: null,
        occurrence_due_at: null,
      },
    ]);

    expect(await screen.findByText(/cash/)).toBeInTheDocument();
    expect(screen.queryByText('Excuse this')).not.toBeInTheDocument();
  });
});
