import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StandingBanner } from './StandingBanner';
import { useChores } from '../api/hooks';

let viewer = 'nika';
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ me: { id: viewer } }) }));

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const TIERS = [
  {
    id: 1,
    condition: 'more than one missing assignment',
    outcome_kind: 'text',
    amount_cents: null,
    text: "grounded until it's fixed",
  },
];

const STANDING = {
  id: 'c1',
  chore_kind: 'standing',
  assignment_mode: 'fixed',
  fixed_assignee_id: 'nika',
  assignee_ids: [],
  standing_on: true,
  standing_tier_id: 1,
  standing_since: new Date().toISOString(),
  title: 'Missing assignments',
  outcome_tiers: TIERS,
  reward_cents: 0,
  penalty_cents: 0,
};

/** The banner renders nothing in the cases we most need to assert, and a bare
 *  "expect(...).not.toBeInTheDocument()" passes on the first tick — before the fetch has even
 *  resolved — so it would pass just as happily against a leaking banner. This probe shares the
 *  useChores cache and gives those assertions a real anchor to wait on. */
function Probe() {
  const chores = useChores();
  return <span data-testid="probe">{chores.isSuccess ? 'loaded' : 'loading'}</span>;
}

function setup(chores: unknown[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(json(chores)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StandingBanner />
      <Probe />
    </QueryClientProvider>,
  );
}

/** Resolves once the chore list has actually arrived. */
const loaded = () => screen.findByText('loaded');

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  viewer = 'nika';
});

describe('StandingBanner', () => {
  it('says what is in force and since when', async () => {
    setup([STANDING]);

    expect(await screen.findByText("grounded until it's fixed")).toBeInTheDocument();
    expect(screen.getByText(/more than one missing assignment · since today/)).toBeInTheDocument();
  });

  it('renders nothing when the state is off', async () => {
    setup([{ ...STANDING, standing_on: false, standing_tier_id: null, standing_since: null }]);

    await loaded();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('ignores ordinary scheduled chores', async () => {
    setup([{ ...STANDING, chore_kind: 'scheduled', standing_on: false }]);

    await loaded();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it("does not show one kid's standing state to a sibling", async () => {
    // GET /chores serves every household definition to every kid (spec §15 Q8), so the
    // banner has to narrow it back to the viewer (spec §15 Q1, own data only).
    viewer = 'kira';
    setup([STANDING]);

    await loaded();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.queryByText("grounded until it's fixed")).not.toBeInTheDocument();
  });

  it('shows an all-mode standing chore to each kid it names', async () => {
    viewer = 'kira';
    setup([
      {
        ...STANDING,
        assignment_mode: 'all',
        fixed_assignee_id: null,
        assignee_ids: ['nika', 'kira'],
      },
    ]);

    expect(await screen.findByText("grounded until it's fixed")).toBeInTheDocument();
  });
});
