import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ReviewDetail } from './ReviewDetail';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const due = new Date().toISOString();

const TIERS = [
  { id: 1, condition: 'all A grades', outcome_kind: 'money', amount_cents: 10000, text: null },
  { id: 2, condition: 'at least one B', outcome_kind: 'money', amount_cents: 5000, text: null },
  { id: 3, condition: 'at least one C', outcome_kind: 'money', amount_cents: -5000, text: null },
];

const BASE = {
  id: 'o1',
  chore_id: 'c1',
  assignee_id: 'k1',
  window_open_at: due,
  due_at: due,
  status: 'submitted',
  was_late: false,
  settlement_locked_at: null,
  reward_cents: 0,
  penalty_cents: 0,
  outcome_tiers: null,
  outcome_tier_id: null,
  outcome_tier: null,
  verification_error: null,
};

function setup(occurrence: Record<string, unknown>) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method !== 'GET')
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (method === 'POST') return Promise.resolve(json(occurrence));
    if (url.endsWith('/occurrences/o1')) return Promise.resolve(json(occurrence));
    return Promise.resolve(json([]));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReviewDetail id="o1" onDone={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ReviewDetail — tiered outcomes', () => {
  it('offers one button per tier instead of approve/reject', async () => {
    setup({ ...BASE, outcome_tiers: TIERS });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /all A grades/ })).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /at least one B → \+\$50\.00/ })).toBeInTheDocument();
    // a negative tier reads as a penalty, with the sign shown
    expect(screen.getByRole('button', { name: /at least one C → -\$50\.00/ })).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: /^approve$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^reject$/i })).not.toBeInTheDocument();
    // the tier carries the amount, so the manual override makes no sense
    expect(screen.queryByPlaceholderText(/Adjust amount/)).not.toBeInTheDocument();
  });

  it('POSTs the chosen tier with the required reason', async () => {
    const calls = setup({ ...BASE, outcome_tiers: TIERS });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /at least one B/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByPlaceholderText(/^Reason/), {
      target: { value: 'one B in maths' },
    });
    fireEvent.click(screen.getByRole('button', { name: /at least one B/ }));

    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].body).toEqual({
      action: 'tier',
      reason: 'one B in maths',
      tier_id: 2,
    });
  });

  it('will not grade without a reason', async () => {
    const calls = setup({ ...BASE, outcome_tiers: TIERS });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /all A grades/ })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: /all A grades/ }));

    expect(await screen.findByText('Add a reason first.')).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it('shows the grade already given rather than the word Approved', async () => {
    setup({
      ...BASE,
      status: 'approved',
      outcome_tiers: TIERS,
      outcome_tier_id: 3,
      outcome_tier: TIERS[2],
    });

    // the heading names the grade; the tier button for it is still there to re-grade with
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /at least one C → -\$50\.00/ }),
      ).toBeInTheDocument(),
    );
  });

  it('leaves an ordinary chore on approve / reject', async () => {
    setup(BASE);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /^reject$/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Adjust amount/)).toBeInTheDocument();
  });
});
