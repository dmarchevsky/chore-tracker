import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PenaltyApply } from './PenaltyApply';
import type { Chore } from '../../api/types';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const KIDS = [
  { id: 'k1', display_name: 'Alice', is_active: true },
  { id: 'k2', display_name: 'Bea', is_active: true },
];

const RULE = {
  id: 'c4',
  chore_kind: 'penalty',
  title: 'Bike left out',
  assignment_mode: 'fixed',
  fixed_assignee_id: 'k1',
  assignee_ids: [],
  active: true,
  outcome_tiers: [
    {
      id: 1,
      condition: 'left in the driveway',
      outcome_kind: 'money',
      amount_cents: -200,
      text: null,
    },
    {
      id: 2,
      condition: 'again the same week',
      outcome_kind: 'money',
      amount_cents: -500,
      text: null,
    },
  ],
} as unknown as Chore;

function setup(chore: Chore = RULE) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method !== 'GET')
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });

    if (method === 'POST')
      return Promise.resolve(json({ id: 'l9', kind: 'penalty', amount_cents: -200 }, 201));
    if (url.includes('/children')) return Promise.resolve(json(KIDS));
    return Promise.resolve(json([]));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PenaltyApply chore={chore} />
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('PenaltyApply', () => {
  it('offers only the kids the rule targets', async () => {
    setup();

    await waitFor(() => expect(screen.getByRole('option', { name: 'Alice' })).toBeInTheDocument());
    // The backend 409s on anyone else (services/penalties.py) — offering the name would
    // just be a dead end.
    expect(screen.queryByRole('option', { name: 'Bea' })).not.toBeInTheDocument();
  });

  it('charges the picked condition only after a confirm', async () => {
    const calls = setup();

    await waitFor(() => expect(screen.getByRole('option', { name: 'Alice' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Who'), { target: { value: 'k1' } });
    fireEvent.click(screen.getByRole('radio', { name: /again the same week/ }));
    fireEvent.change(screen.getByLabelText(/^Note/), { target: { value: 'twice now' } });

    fireEvent.click(screen.getByRole('button', { name: 'Charge…' }));
    // Nothing has moved yet — money-moving controls elsewhere sit behind a review screen.
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    expect(screen.getByText(/Take/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Yes, charge it' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));

    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toMatch(/\/penalties$/);
    expect(post.body).toEqual({
      chore_id: 'c4',
      child_id: 'k1',
      tier_id: 2,
      note: 'twice now',
    });
  });

  it('sends an override as a positive magnitude, leaving the sign to the backend', async () => {
    const calls = setup();

    await waitFor(() => expect(screen.getByRole('option', { name: 'Alice' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Who'), { target: { value: 'k1' } });
    fireEvent.click(screen.getByRole('radio', { name: /left in the driveway/ }));
    fireEvent.change(screen.getByLabelText(/Different amount/), { target: { value: '3.50' } });

    fireEvent.click(screen.getByRole('button', { name: 'Charge…' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes, charge it' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));

    const body = calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>;
    expect(body.amount_override_cents).toBe(350);
  });

  it('will not charge before a kid and a condition are picked', async () => {
    setup();

    await waitFor(() => expect(screen.getByRole('option', { name: 'Alice' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Charge…' })).toBeDisabled();
  });

  it('says a deactivated rule cannot be charged', async () => {
    setup({ ...RULE, active: false });

    expect(await screen.findByText(/deactivated/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Charge…' })).not.toBeInTheDocument();
  });
});
