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

function renderInbox(chores: unknown[] = [], route = '/admin') {
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
    if (url.includes('/chores'))
      // The bare stub has no chore_kind, so it is not a standing chore and the section
      // filters it out — do not "tidy" it into a full Chore or the queue tests shift.
      return Promise.resolve(json([{ id: 'c1', title: 'Empty the sink' }, ...chores]));
    if (url.endsWith('/children')) return Promise.resolve(json([{ id: 'k1', display_name: 'Mo' }]));
    if (url.endsWith('/occurrences/o1')) return Promise.resolve(json(occurrence));
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
});
