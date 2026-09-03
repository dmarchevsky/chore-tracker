import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Rules } from './Rules';

let viewer = 'kid-a';
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ me: { id: viewer } }) }));

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const BASE = {
  chore_kind: 'scheduled',
  assignment_mode: 'fixed',
  fixed_assignee_id: 'kid-a',
  assignee_ids: [],
  outcome_tiers: null,
  reward_cents: 100,
  penalty_cents: 0,
  photo_count: 1,
  photo_prompts: [],
  proof_type: 'checkbox',
  cadence: 'daily',
  due_time: '08:00:00',
  window_open_offset_s: -12 * 3600,
  standing_on: false,
};

const MINE = { ...BASE, id: 'c1', title: 'Dishes' };
const POOL = {
  ...BASE,
  id: 'c2',
  title: 'Bins',
  assignment_mode: 'anyone',
  fixed_assignee_id: null,
};
const SIBLING = { ...BASE, id: 'c3', title: 'Beas job', fixed_assignee_id: 'kid-b' };
const PENALTY = {
  ...BASE,
  id: 'c4',
  title: 'Bike left out',
  chore_kind: 'penalty',
  cadence: 'penalty',
  proof_type: 'none',
  reward_cents: 0,
  outcome_tiers: [
    {
      id: 1,
      condition: 'left in the driveway',
      outcome_kind: 'money',
      amount_cents: -200,
      text: null,
    },
  ],
};

function setup(chores: unknown[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(json(chores)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Rules />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  viewer = 'kid-a';
});

describe('Rules', () => {
  it("shows the kid's own chores and the anyone pool", async () => {
    setup([MINE, POOL]);

    expect(await screen.findByText('Dishes')).toBeInTheDocument();
    expect(screen.getByText('Bins')).toBeInTheDocument();
  });

  it("does not show a sibling's chore", async () => {
    // The server already scopes a kid's list (spec §15 Q1); the screen must not widen it
    // back out from a cached response.
    setup([MINE, SIBLING]);

    expect(await screen.findByText('Dishes')).toBeInTheDocument();
    expect(screen.queryByText('Beas job')).not.toBeInTheDocument();
  });

  it('shows a penalty rule with what it costs', async () => {
    // Published in advance on purpose: the kid reads the price before it is ever charged
    // (spec §4.8, §15 Q8).
    setup([MINE, PENALTY]);

    expect(await screen.findByText('Costs you money')).toBeInTheDocument();
    expect(screen.getByText('Bike left out')).toBeInTheDocument();
    expect(screen.getByText(/left in the driveway/)).toBeInTheDocument();
    expect(screen.getByText('-$2.00')).toBeInTheDocument();
  });

  it("does not show a sibling's penalty rule", async () => {
    setup([{ ...PENALTY, fixed_assignee_id: 'kid-b' }]);

    await screen.findByText('The rules');
    expect(screen.queryByText('Bike left out')).not.toBeInTheDocument();
    expect(screen.queryByText('Costs you money')).not.toBeInTheDocument();
  });

  it('shows when a scheduled chore happens', async () => {
    // Without this a daily chore and a Saturday-only one look identical on this screen —
    // the whole point of showing a kid their rules is that nothing is a surprise (§15 Q8).
    setup([{ ...MINE, cadence: 'weekly(on=[SAT])' }]);

    expect(await screen.findByText(/Every Sat, due /)).toBeInTheDocument();
    expect(screen.getByText(/opens .* the day before/)).toBeInTheDocument();
  });

  it('shows no schedule line on rules that have no schedule', async () => {
    // A standing chore is a state a parent flips and a penalty rule is a price list; the
    // backend fills their schedule columns with defaults, so printing them would be a lie.
    setup([
      { ...MINE, id: 'c5', title: 'Room tidy', chore_kind: 'standing', cadence: 'standing' },
      PENALTY,
    ]);

    await screen.findByText('Room tidy');
    expect(screen.queryByText(/due /)).not.toBeInTheDocument();
  });

  it('shows an all-mode chore to each kid it names', async () => {
    viewer = 'kid-b';
    setup([{ ...MINE, assignment_mode: 'all', fixed_assignee_id: null, assignee_ids: ['kid-b'] }]);

    expect(await screen.findByText('Dishes')).toBeInTheDocument();
  });
});
