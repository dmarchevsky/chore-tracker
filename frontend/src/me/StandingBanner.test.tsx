import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StandingBanner } from './StandingBanner';

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
  standing_on: true,
  standing_tier_id: 1,
  standing_since: new Date().toISOString(),
  title: 'Missing assignments',
  outcome_tiers: TIERS,
  reward_cents: 0,
  penalty_cents: 0,
};

function setup(chores: unknown[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(json(chores)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StandingBanner />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('StandingBanner', () => {
  it('says what is in force and since when', async () => {
    setup([STANDING]);

    expect(await screen.findByText("grounded until it's fixed")).toBeInTheDocument();
    expect(screen.getByText(/more than one missing assignment · since today/)).toBeInTheDocument();
  });

  it('renders nothing when the state is off', async () => {
    setup([{ ...STANDING, standing_on: false, standing_tier_id: null, standing_since: null }]);

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('ignores ordinary scheduled chores', async () => {
    setup([{ ...STANDING, chore_kind: 'scheduled', standing_on: false }]);

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });
});
