import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Inbox } from './Inbox';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const due = new Date().toISOString();

const occurrence = {
  id: 'o1',
  chore_id: 'c1',
  assignee_id: 'k1',
  window_open_at: due,
  due_at: due,
  status: 'submitted',
  was_late: false,
  settlement_locked_at: null,
  reward_cents: 200,
  penalty_cents: 0,
  verification_error: null,
};

const hourAgo = new Date(Date.now() - 3600_000).toISOString();
const tomorrow = new Date(Date.now() + 86_400_000).toISOString();
const nextWeek = new Date(Date.now() + 7 * 86_400_000).toISOString();

const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString();

function miss(over: Record<string, unknown>) {
  return {
    ...occurrence,
    status: 'missed',
    reward_cents: 0,
    penalty_cents: 100,
    due_at: hourAgo,
    window_open_at: hourAgo,
    ...over,
  };
}

/** Newest first, the way the query returns them: Mo's fresh miss, Mo's older miss of the same
 *  chore (folded into the first), Ana's miss of another chore, and one from a month ago. */
const missed = [
  miss({ id: 'o2', chore_id: 'c2' }),
  miss({ id: 'o6', chore_id: 'c2', due_at: daysAgo(2), window_open_at: daysAgo(2) }),
  miss({ id: 'o7', chore_id: 'c4', assignee_id: 'k2', due_at: daysAgo(3) }),
  miss({ id: 'o8', chore_id: 'c5', due_at: daysAgo(30) }),
];

/** Two turns of the same chore for Mo, plus Ana's — the parent should see Mo's next one and
 *  Ana's, not every day of the horizon. */
const pending = [
  {
    ...occurrence,
    id: 'o3',
    chore_id: 'c3',
    due_at: tomorrow,
    window_open_at: tomorrow,
    status: 'pending',
  },
  {
    ...occurrence,
    id: 'o4',
    chore_id: 'c3',
    due_at: nextWeek,
    window_open_at: nextWeek,
    status: 'pending',
  },
  {
    ...occurrence,
    id: 'o5',
    chore_id: 'c3',
    assignee_id: 'k2',
    due_at: nextWeek,
    window_open_at: nextWeek,
    status: 'pending',
  },
];

const submission = {
  id: 's1',
  kind: 'photo',
  source: 'camera',
  note: null,
  flags: ['DUPLICATE_SUSPECTED'],
  created_at: due,
  geo_distance_m: null,
  geo_within: null,
  media: [],
};

const verification = {
  id: 'v1',
  kind: 'llm',
  verdict: 'fail',
  confidence: 0.91,
  reasoning: 'flags: DUPLICATE_SUSPECTED; #1:no(0.91)',
  child_message: null,
  checks: [{ id: 1, answer: 'no', confidence: 0.91, evidence: 'this is a drum set, not a dog' }],
  image_quality_issue: 'none',
  created_by: 'system',
  created_at: due,
};

const dispute = {
  id: 'd1',
  occurrence_id: 'o1',
  author_user_id: 'k1',
  message: 'I did walk him, the photo is just dark',
  status: 'open',
  status_at_filing: 'rejected',
  resolution_note: null,
  resolved_at: null,
  created_at: due,
  chore_title: 'Empty the sink',
  author_name: 'Mo',
  occurrence_status: 'rejected',
  occurrence_due_at: due,
};

const TIER = {
  id: 1,
  condition: 'more than one missing assignment',
  outcome_kind: 'text',
  amount_cents: null,
  text: "grounded until it's fixed",
};

// Deliberately not titled "Empty the sink": queueRow() below picks the LAST match of that
// title, so a standing chore sharing it would quietly capture the helper.
const standingOn = {
  id: 'c9',
  title: 'Missing assignments',
  chore_kind: 'standing',
  active: true,
  standing_on: true,
  standing_tier_id: 1,
  standing_since: '2026-08-20T10:00:00Z',
  outcome_tiers: [TIER],
  assignment_mode: 'fixed',
  fixed_assignee_id: 'k1',
  assignee_ids: [],
};
const standingOff = {
  ...standingOn,
  id: 'c8',
  title: 'Late homework',
  standing_on: false,
  standing_tier_id: null,
  standing_since: null,
};
const standingRetired = { ...standingOn, id: 'c7', title: 'Old rule', active: false };

const penalty = {
  id: 'p1',
  title: 'Missed curfew',
  description: '',
  chore_kind: 'penalty',
  active: true,
  standing_on: false,
  standing_tier_id: null,
  standing_since: null,
  outcome_tiers: [
    { id: 1, condition: 'first time', outcome_kind: 'money', amount_cents: -200, text: null },
    { id: 2, condition: 'again this week', outcome_kind: 'money', amount_cents: -500, text: null },
  ],
  assignment_mode: 'all',
  fixed_assignee_id: null,
  // Ana is a kid but not on this rule — the select must not offer her, because the backend
  // 409s on anyone the rule does not target (services/penalties.py).
  assignee_ids: ['k1'],
};
const penaltyRetired = { ...penalty, id: 'p2', title: 'Old fine', active: false };

function renderInbox(chores: unknown[] = [], route = '/admin', misses: unknown[] = missed) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.includes('inbox=true')) return Promise.resolve(json([occurrence]));
    if (url.includes('/state/history'))
      return Promise.resolve(
        json([
          {
            id: 'e1',
            chore_id: 'c9',
            actor_user_id: null,
            state: true,
            tier_id: 1,
            tier: TIER,
            note: 'third this week',
            created_at: '2026-08-20T10:00:00Z',
          },
        ]),
      );
    if (url.includes('status=missed')) return Promise.resolve(json(misses));
    if (url.includes('status=pending')) return Promise.resolve(json(pending));
    if (url.includes('/penalties'))
      return Promise.resolve(json({ id: 'l1', amount_cents: -500, kind: 'penalty' }));
    if (url.includes('/chores'))
      // The bare stub has no chore_kind, so it is not a standing chore and the section
      // filters it out — do not "tidy" it into a full Chore or the queue tests shift.
      return Promise.resolve(
        json([
          { id: 'c1', title: 'Empty the sink' },
          { id: 'c2', title: 'Sweep the porch' },
          { id: 'c3', title: 'Water the plants' },
          { id: 'c4', title: 'Fold laundry' },
          { id: 'c5', title: 'Rake leaves' },
          ...chores,
        ]),
      );
    if (url.endsWith('/children'))
      return Promise.resolve(
        json([
          { id: 'k1', display_name: 'Mo' },
          { id: 'k2', display_name: 'Ana' },
        ]),
      );
    if (url.endsWith('/occurrences/o1')) return Promise.resolve(json(occurrence));
    if (url.endsWith('/occurrences/o2')) return Promise.resolve(json(missed[0]));
    if (url.includes('/disputes')) return Promise.resolve(json([dispute]));
    if (url.includes('/submissions')) return Promise.resolve(json([submission]));
    if (url.includes('/verifications')) return Promise.resolve(json([verification]));
    return Promise.resolve(json([]));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/admin" element={<Inbox />} />
          <Route path="/admin/review/:id" element={<Inbox />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => renderInbox());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** The chore title appears in the disputes section too; the queue row is the last one. */
async function queueRow() {
  await waitFor(() => expect(screen.getAllByText('Empty the sink').length).toBeGreaterThan(0));
  return screen.getAllByText('Empty the sink').at(-1)!;
}

describe('admin Inbox', () => {
  it('lists items waiting for review and opens the detail pane', async () => {
    (await queueRow()).click();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText(/^Reason — your kid will see this$/)).toBeInTheDocument();
  });

  it('names the status and the kid instead of printing the raw enum', async () => {
    await queueRow();

    expect(screen.getByText('Checking…')).toBeInTheDocument();
    expect(screen.queryByText('submitted')).not.toBeInTheDocument();
    expect(screen.getAllByText(/^Mo ·/).length).toBeGreaterThan(0);
  });

  it('surfaces a kid’s “this isn’t right” instead of leaving it in a push notification', async () => {
    await waitFor(() =>
      expect(screen.getByText(/Kids say something is wrong \(1\)/)).toBeInTheDocument(),
    );
    expect(screen.getAllByText(/the photo is just dark/).length).toBeGreaterThan(0);

    screen.getByText(/the photo is just dark/).click();
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/reply — your kid will see this/i)).toBeInTheDocument(),
    );
  });

  it('leads with why the item is held and what the model actually found', async () => {
    (await queueRow()).click();

    // The flag is explained, not shouted as an enum...
    await waitFor(() =>
      expect(screen.getAllByText(/looks like a photo sent before/i).length).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/DUPLICATE_SUSPECTED/)).not.toBeInTheDocument();
    // ...and the model's own justification is on screen, not buried in raw JSON.
    expect(screen.getByText(/drum set, not a dog/i)).toBeInTheDocument();
    expect(screen.getByText(/The AI says: Fail/i)).toBeInTheDocument();
  });

  it('lists a standing chore that is in force, with what it is and since when', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([standingOn]);

    expect(await screen.findByText('Missing assignments')).toBeInTheDocument();
    expect(screen.getByText("grounded until it's fixed")).toBeInTheDocument();
    expect(screen.getByText('In force')).toBeInTheDocument();
    // never the raw boolean
    expect(screen.queryByText('true')).not.toBeInTheDocument();
  });

  it('lists a standing chore that is off, so it can be turned on', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([standingOff]);

    expect(await screen.findByText('Late homework')).toBeInTheDocument();
    expect(screen.getByText('Off')).toBeInTheDocument();
  });

  it('leaves a retired standing chore out of the inbox', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([standingRetired]);

    await waitFor(() => expect(screen.getAllByText('Empty the sink').length).toBeGreaterThan(0));
    expect(screen.queryByText('Old rule')).not.toBeInTheDocument();
  });

  it('opens the flip controls instead of the review pane', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([standingOn]);

    fireEvent.click(await screen.findByText('Missing assignments'));

    expect(
      await screen.findByRole('button', { name: 'more than one missing assignment' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Turn it off' })).toBeInTheDocument();
    expect(screen.getByLabelText('Flip note')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it('shows the flip history in the pane', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([standingOn]);

    fireEvent.click(await screen.findByText('Missing assignments'));

    expect(await screen.findByText(/third this week/)).toBeInTheDocument();
  });

  it('still opens the occurrence pane from a push deep link', async () => {
    // The selection is tagged now; the route stays the one untagged input and must keep
    // meaning "an occurrence", or every push notification lands on the wrong pane.
    cleanup();
    vi.restoreAllMocks();
    renderInbox([standingOn], '/admin/review/o1');

    expect(await screen.findByRole('button', { name: /^approve$/i })).toBeInTheDocument();
  });

  it('lists the active penalty rules with what each condition costs', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([penalty]);

    expect(await screen.findByText('Penalties')).toBeInTheDocument();
    expect(screen.getByText('Missed curfew')).toBeInTheDocument();
    expect(screen.getByText(/first time -\$2\.00/)).toBeInTheDocument();
    expect(screen.getByText(/again this week -\$5\.00/)).toBeInTheDocument();
  });

  it('leaves a deactivated penalty rule out — it cannot be charged', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([penaltyRetired]);

    await waitFor(() => expect(screen.getAllByText('Empty the sink').length).toBeGreaterThan(0));
    expect(screen.queryByText('Old fine')).not.toBeInTheDocument();
    expect(screen.queryByText('Penalties')).not.toBeInTheDocument();
  });

  it('opens the charge form, offering only the kids the rule targets', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([penalty]);

    fireEvent.click(await screen.findByRole('button', { name: 'Charge' }));

    expect(await screen.findByText('Charge this')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Mo' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Ana' })).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'again this week' })).toBeInTheDocument();
    // the penalty pane, not the review pane
    expect(screen.queryByRole('button', { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it('charges the kid with the override and note, but only after a second tap', async () => {
    cleanup();
    vi.restoreAllMocks();
    renderInbox([penalty]);
    // renderInbox already spies on fetch; read the charge back off its calls rather than
    // wrapping the mock, which loses the stub's own routing.
    const charges = () =>
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(
          ([input, init]) =>
            String(input).includes('/penalties') && (init?.method ?? 'GET') === 'POST',
        )
        .map(([, init]) => JSON.parse(String(init!.body)));

    fireEvent.click(await screen.findByRole('button', { name: 'Charge' }));
    fireEvent.change(await screen.findByRole('combobox'), { target: { value: 'k1' } });
    fireEvent.click(screen.getByRole('radio', { name: 'again this week' }));
    fireEvent.change(screen.getByLabelText(/Different amount this time/), {
      target: { value: '3.50' },
    });
    fireEvent.change(screen.getByPlaceholderText(/Why\? Your kid reads this\./), {
      target: { value: 'home at 1am' },
    });

    // nothing is charged on the first tap — it only asks
    fireEvent.click(screen.getByRole('button', { name: 'Charge…' }));
    expect(charges()).toHaveLength(0);
    expect(screen.getByText(/Take/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Yes, charge it' }));

    await waitFor(() => expect(charges()).toHaveLength(1));
    expect(charges()[0]).toEqual({
      chore_id: 'p1',
      child_id: 'k1',
      tier_id: 2,
      // a positive magnitude — the sign is the backend's
      amount_override_cents: 350,
      note: 'home at 1am',
    });
  });

  it('keeps the pane open and repaints when a flip lands', async () => {
    cleanup();
    vi.restoreAllMocks();
    // first /chores call says off, every later one says in force — i.e. the invalidation
    // after the flip returns fresh data
    let flipped = false;
    // the SAME chore, flipped — not a different fixture, or the pane's lookup by id misses
    const after = {
      ...standingOff,
      standing_on: true,
      standing_tier_id: 1,
      standing_since: '2026-09-01T10:00:00Z',
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input);
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/state')) {
        flipped = true;
        return Promise.resolve(json(after));
      }
      if (url.includes('/state/history')) return Promise.resolve(json([]));
      if (url.includes('inbox=true')) return Promise.resolve(json([]));
      if (url.endsWith('/children'))
        return Promise.resolve(json([{ id: 'k1', display_name: 'Mo' }]));
      if (url.includes('/chores')) return Promise.resolve(json([flipped ? after : standingOff]));
      return Promise.resolve(json([]));
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Inbox />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByText('Late homework'));
    fireEvent.click(
      await screen.findByRole('button', { name: 'more than one missing assignment' }),
    );

    // the pane is still here, now showing the new state — it does not close on success
    expect(await screen.findByText("grounded until it's fixed")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Turn it off' })).toBeInTheDocument();
  });

  it('lists misses the parent has not settled yet, and opens one for a decision', async () => {
    const row = await screen.findByText('Sweep the porch');
    expect(await screen.findByText('Missed (2)')).toBeInTheDocument();
    expect(row.parentElement!.parentElement!.textContent).toContain('Mo');

    row.click();

    // A miss has no submission to look at, but it can still be excused.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^excuse$/i })).toBeInTheDocument(),
    );
  });

  it('keeps one missed row per chore and kid, and says how many it stands for', async () => {
    const row = await screen.findByText('Sweep the porch');

    // Mo missed it twice; the older one folds into the newer rather than repeating.
    expect(screen.getAllByText('Sweep the porch')).toHaveLength(1);
    expect(row.parentElement!.parentElement!.textContent).toContain('1 more like this');
    // Ana's miss of another chore is its own row, and stands alone.
    const ana = screen.getByText('Fold laundry');
    expect(ana.parentElement!.parentElement!.textContent).toContain('Ana');
    expect(ana.parentElement!.parentElement!.textContent).not.toContain('more like this');
  });

  it('leaves misses older than a week to History, and links there for the rest', async () => {
    await screen.findByText('Sweep the porch');

    expect(screen.queryByText('Rake leaves')).not.toBeInTheDocument();
    const link = screen.getByRole('link', { name: '2 more in History' });
    expect(link).toHaveAttribute('href', '/admin/history?status=missed');
  });

  it('caps the missed list however many are outstanding', async () => {
    cleanup();
    vi.restoreAllMocks();
    // Eight distinct chores, all missed today — nothing for the window or the dedupe to drop.
    const many = Array.from({ length: 8 }, (_, i) => miss({ id: `m${i}`, chore_id: `c1${i}` }));
    renderInbox([], '/admin', many);

    expect(await screen.findByText('Missed (5)')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '3 more in History' })).toBeInTheDocument();
  });

  it('shows only the next turn of each chore and kid under Coming up, and leaves it inert', async () => {
    await screen.findByText('Coming up');
    // o3 (Mo, tomorrow) and o5 (Ana) survive; o4 is Mo's second turn on the same chore.
    const rows = screen.getAllByText('Water the plants');
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.parentElement!.parentElement!.textContent)).toEqual([
      expect.stringContaining('Mo'),
      expect.stringContaining('Ana'),
    ]);
    rows.forEach((r) => expect(r.closest('button')).toBeNull());
  });

  it('keeps missed and upcoming rows out of bulk approve', async () => {
    await screen.findByText('Coming up');
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
  });
});
